# app/domain/storage.py

"""
업로드 이미지의 저장 위치와 파일명 규칙 — 로컬 파일 / S3 이중 모드.

배포가 "백엔드 3대 + 컨테이너"로 확정되면서 로컬 디스크 저장이 성립하지 않게 됐다:
A 컨테이너에 올린 사진을 B 컨테이너가 서빙할 수 없고, 컨테이너가 교체되면 파일이
통째로 사라진다. 그래서 운영에서는 S3에 저장하고, DB의 image_url에는 S3 공개 URL을
담는다 — 브라우저가 S3에서 직접 받으므로 웹 계층은 이미지 트래픽을 만지지 않는다
(stateless).

**모드는 S3_BUCKET 환경변수 하나로 갈린다.**
    설정됨   → S3 저장. 컨테이너의 IAM 역할(ECS Task Role / EKS IRSA)로 인증하므로
              액세스 키를 환경변수에 넣지 않는다.
    비어 있음 → 기존 로컬 파일 저장. 로컬 개발·CI·단일 호스트 시연은 AWS 없이
              지금까지와 똑같이 동작한다.

설정을 config.py에 모으는 관행이 있지만, S3 설정은 소비자가 이 모듈 하나뿐이라
여기서 읽는다(memo.py와 같은 판단). 다른 곳에서도 쓰게 되면 config.py로 옮긴다.

크롤링 이미지는 여기와 무관하다 — 수집처 CDN의 URL을 그대로 참조하며, 그건 남의
파일이라 저장하지도 지우지도 않는다. 이 모듈은 기업고객이 올린 사진만 다룬다.

**파일명은 우리가 짓는다.** 원본 이름을 쓰면 두 가지가 들어온다 — 경로 조작
("../../etc/passwd")과 확장자 위조("사진.jpg.php"). 이름을 새로 만들면 둘 다
성립하지 않는다. 원본 이름이 필요하면 DB 컬럼에 따로 담을 일이지 파일명으로 쓸
값이 아니다.

**설정 오류는 배포 시점에 드러나야 한다.** 이 모듈이 지키는 세 가지:
    - 운영(APP_ENV=production)인데 S3_BUCKET 이 비어 있으면 기동을 거부한다.
      조용히 로컬 디스크로 떨어지면 파드 3대에서 사진이 깨지는데, 에러가 없어서
      한참 뒤에야 안다. 단일 호스트 시연처럼 일부러 로컬 모드를 쓰려면
      ALLOW_LOCAL_STORAGE=true 로 명시한다.
    - S3 모드는 첫 /ready 에서 프로브 객체를 put→delete 해 본다(check_storage).
      IAM 권한·리전·버킷 이름 오타가 첫 업로드가 아니라 기동 직후에 잡힌다.
      한 번 성공하면 다시 묻지 않는다 — 운영 중 S3 장애로 파드를 빼는 일은 없다.
    - 저장 실패는 StorageUnavailable 하나로 닫는다. 라우터는 botocore 예외를 몰라도
      되고, 503 + Retry-After 로 "지금은 안 되니 잠시 후"를 정직하게 돌려줄 수 있다.
"""

import asyncio
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import IS_PRODUCTION, UPLOAD_DIR

logger = logging.getLogger(__name__)

# S3 버킷 이름. 비어 있으면 로컬 파일 모드다.
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()

# 리전. IRSA 웹훅과 태스크 데피니션이 AWS_REGION 을 넣어 주지만, 없을 수도 있어
# AWS_DEFAULT_REGION 까지 본다. 공개 주소를 만들 때만 쓴다(boto3 는 자기가 읽는다).
AWS_REGION = os.getenv("AWS_REGION", "").strip() or os.getenv("AWS_DEFAULT_REGION", "").strip()

# 로컬 디스크 모드를 운영에서 허용하는 명시적 스위치. 단일 호스트 시연용.
ALLOW_LOCAL_STORAGE = os.getenv("ALLOW_LOCAL_STORAGE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


def _default_public_base(bucket: str, region: str) -> str:
    """
    버킷의 기본 공개 주소를 만든다. 리전을 알면 리전 포함 주소로.

    리전 없는 https://버킷.s3.amazonaws.com 은 us-east-1 밖의 버킷에서 307
    리다이렉트를 탄다. 브라우저가 <img> 에서 그 리다이렉트를 따라가긴 하지만,
    버킷을 만든 직후에는 DNS 전파 전이라 실패하기도 한다. 리전을 알 수 있는데
    굳이 리다이렉트를 탈 이유가 없다.
    """
    if not bucket:
        return ""

    if region:
        return f"https://{bucket}.s3.{region}.amazonaws.com"

    return f"https://{bucket}.s3.amazonaws.com"


# 화면이 참조할 공개 주소의 앞부분. CloudFront를 붙이면 그 도메인을 준다.
# 비워두면 버킷 주소로 만든다 — AWS_REGION 이 있으면 리전 포함 주소다.
S3_PUBLIC_BASE = os.getenv("S3_PUBLIC_BASE", "").strip().rstrip("/") or _default_public_base(
    S3_BUCKET, AWS_REGION
)


def _guard_production_storage(*, production: bool, bucket: str, allow_local: bool) -> None:
    """
    운영에서 S3 설정 누락을 기동 거부로 바꾼다. config._secret_env 와 같은 판단이다.

    RuntimeError 를 임포트 단계에서 올리면 파드가 CrashLoopBackOff 가 되고 로그
    첫 줄에 이유가 남는다. 사진이 파드마다 다르게 보이는 상태로 트래픽을 받는
    것보다 낫다.
    """
    if production and not bucket and not allow_local:
        raise RuntimeError(
            "APP_ENV=production 인데 S3_BUCKET 이 비어 있습니다. 컨테이너 여러 대에서 "
            "로컬 디스크 저장은 성립하지 않습니다(파드마다 사진이 다르고 교체 시 사라짐). "
            "S3_BUCKET 을 설정하거나, 단일 호스트 시연이면 ALLOW_LOCAL_STORAGE=true 로 "
            "명시하세요."
        )


_guard_production_storage(
    production=IS_PRODUCTION, bucket=S3_BUCKET, allow_local=ALLOW_LOCAL_STORAGE
)


class StorageUnavailable(Exception):
    """
    저장소에 쓸 수 없다 — S3 거부/연결 실패, 로컬 디스크 권한·용량.

    라우터는 이 예외 하나만 잡아 503 으로 바꾼다. botocore 의 예외 계층을 라우터가
    알 필요가 없고, 로컬/S3 모드가 같은 계약을 갖게 된다.
    """


# S3 프로브 결과 캐시. 성공하면 다시 묻지 않고, 실패는 잠시 뒤 다시 시도한다.
_PROBE_RETRY_SECONDS = 60
_probe_ok = False
_probe_error: str | None = None
_probe_at = 0.0

# 프로브가 지금 돌고 있는지. 이벤트 루프는 await 지점에서만 다른 코루틴에게 넘어가므로,
# to_thread 로 넘기기 **직전에** 이 값을 세우면 락 없이도 동시 프로브가 하나로 좁혀진다.
# (asyncio.Lock 을 모듈 전역에 두면 처음 쓴 이벤트 루프에 묶여서, 테스트처럼 루프를
#  갈아끼우는 환경에서 터진다. 여기서는 그 위험을 살 이유가 없다.)
_probe_running = False

# 확장자 → Content-Type. 이걸 안 넣으면 S3가 binary/octet-stream으로 응답해서
# 브라우저가 이미지를 그리는 대신 내려받으려 든다.
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# boto3 클라이언트 캐시. 요청마다 만들면 자격증명 조회가 반복된다.
_s3 = None


def _get_s3():
    """
    S3 클라이언트를 만든다(1회) — boto3는 여기서 지연 임포트한다.

    최상단에서 임포트하지 않는 이유: 로컬 개발·CI는 S3 모드를 쓰지 않으므로
    boto3가 없어도 앱이 떠야 한다. S3_BUCKET을 설정한 배포 이미지에만
    boto3를 설치한다 (uv add boto3).
    """
    global _s3

    if _s3 is None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise RuntimeError(
                "S3_BUCKET이 설정됐지만 boto3가 없습니다. 'uv add boto3'로 설치하세요."
            ) from exc

        # 리전을 명시한다. boto3 는 AWS_DEFAULT_REGION 만 읽고 AWS_REGION 은 버전에
        # 따라 무시해서, 리전이 비면 글로벌 엔드포인트(s3.amazonaws.com)로 가 리다이렉트를
        # 탄다. 우리가 읽은 값을 그대로 넘기면 어느 쪽 변수를 줬든 같은 리전으로 간다.
        #
        # 타임아웃을 짧게 못 박는다. botocore 기본값은 연결·읽기 각 60초에 재시도까지
        # 붙어서, 네트워크가 애매하게 죽으면(보안 그룹 누락, VPC 엔드포인트 오설정)
        # 요청 하나가 분 단위로 매달린다. S3 는 같은 리전 안이라 정상이면 수십 ms 이고,
        # 못 붙으면 빨리 실패해서 503 으로 알려주는 편이 낫다.
        #
        # total_max_attempts 는 **초기 요청을 포함한** 총 시도 수다(max_attempts 는
        # 모드에 따라 "추가 재시도 횟수"로 읽혀 헷갈린다). 2 = 처음 한 번 + 재시도 한 번.
        _s3 = boto3.client(
            "s3",
            region_name=AWS_REGION or None,
            config=Config(
                connect_timeout=2,
                read_timeout=3,
                retries={"mode": "standard", "total_max_attempts": 2},
            ),
        )

    return _s3


def build_object_name(extension: str) -> str:
    """
    저장할 상대 경로(=S3 키)를 만든다. 예: 2026/08/3f9a1c2b8e4d5a67.jpg

    연·월로 나누는 이유는 한 디렉토리(프리픽스)에 파일이 수만 개 쌓이면 목록
    조회가 느려지고 백업·정리가 번거로워지기 때문이다.

    이름은 난수다. 순번을 쓰면 남의 이미지 주소를 세어 볼 수 있다 — 판매자가 아직
    공개하지 않은 매물의 사진이 주소만으로 노출된다.
    """
    now = datetime.now(UTC)

    return f"{now:%Y/%m}/{secrets.token_hex(16)}{extension}"


def resolve_upload_path(object_name: str) -> Path:
    """
    (로컬 모드) 상대 경로를 실제 저장 경로로 바꾼다. 업로드 루트를 벗어나면 ValueError.

    경로 조작 방어다. build_object_name이 만든 이름만 쓰는 한 벗어날 수 없지만,
    나중에 DB에 담긴 값을 그대로 넘기는 호출부가 생길 수 있다. 그때 이 검사가
    유일한 방어선이 된다. (S3 모드는 키가 경로로 해석되지 않아 이 문제가 없다.)
    """
    root = UPLOAD_DIR.resolve()
    target = (root / object_name).resolve()

    if not target.is_relative_to(root):
        raise ValueError("업로드 경로를 벗어났습니다.")

    return target


def save_image(data: bytes, extension: str) -> str:
    """
    이미지를 저장하고 저장 이름(=키)을 돌려준다.

    S3 put은 동기 호출이라 업로드 요청 처리 중 짧게(수십~수백 ms) 이벤트 루프를
    잡는다. 로컬 디스크 쓰기도 마찬가지였으므로 새로 생긴 비용은 아니고, 업로드는
    기업고객 전용 저빈도 경로라 시연 규모에서는 문제가 안 된다. 트래픽이 커지면
    to_thread로 옮길 지점이다.
    """
    object_name = build_object_name(extension)

    if S3_BUCKET:
        try:
            _get_s3().put_object(
                Bucket=S3_BUCKET,
                Key=object_name,
                Body=data,
                ContentType=_CONTENT_TYPES.get(extension, "application/octet-stream"),
                # 이름이 난수라 내용이 바뀔 일이 없다 — 브라우저·CDN이 마음껏 캐시해도 된다.
                CacheControl="public, max-age=31536000, immutable",
            )
        except Exception as exc:  # noqa: BLE001 — botocore 예외 계층 전체를 한 종류로 닫는다
            # 예외 문자열에는 버킷·키·요청 ID 가 섞인다. 타입 이름만 남기고 원인은 체인으로.
            logger.warning("S3 업로드 실패: %s (%s)", object_name, type(exc).__name__)
            raise StorageUnavailable(f"S3 업로드 실패: {type(exc).__name__}") from exc

        logger.info("S3 업로드: s3://%s/%s (%d바이트)", S3_BUCKET, object_name, len(data))
    else:
        try:
            path = resolve_upload_path(object_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            logger.warning("로컬 저장 실패: %s (%s)", object_name, type(exc).__name__)
            raise StorageUnavailable(f"로컬 저장 실패: {type(exc).__name__}") from exc

    return object_name


def storage_mode() -> str:
    """지금 저장 모드. /ready 응답에 실린다 — 어느 경로가 검사됐는지 알 수 있게."""
    return "s3" if S3_BUCKET else "local"


def _probe_s3() -> str | None:
    """
    S3 에 프로브 객체를 하나 넣었다 지운다. 문제면 예외 타입 이름, 정상이면 None.

    put 과 delete 를 둘 다 해 보는 이유: 앱이 쓰는 권한이 정확히 그 둘이다.
    head_bucket 은 ListBucket 권한을 요구해 다른 것을 검사하게 된다.
    """
    key = f".readycheck/{secrets.token_hex(8)}"

    try:
        client = _get_s3()
        client.put_object(Bucket=S3_BUCKET, Key=key, Body=b"ok")
        client.delete_object(Bucket=S3_BUCKET, Key=key)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 "못 쓴다" 하나로 보고한다
        return type(exc).__name__

    return None


async def check_storage() -> str | None:
    """
    저장소에 실제로 쓸 수 있는지 확인한다. 문제면 예외 타입 이름, 정상이면 None.

    **로컬 모드**는 매번 파일을 써 본다. 실제 사례가 이유다: 컨테이너의 업로드
    볼륨이 root 소유로 만들어져 앱 계정이 못 쓰는데, 코드 테스트로는 잡을 수 없고
    (테스트는 개발자 PC 권한으로 돈다) 사진 업로드를 눌러보고서야 500으로 드러났다.

    **S3 모드**는 "처음 성공할 때까지만" 프로브한다. IAM 역할 누락·버킷 이름 오타·
    리전 불일치는 전부 배포 설정 오류라 기동 직후에 드러나야 하고, 그 확인은
    put/delete 한 쌍이면 된다(비용·로그는 파드당 몇 번). 한 번 성공한 뒤에는 다시
    묻지 않는다 — 운영 중 S3 장애는 업로드 요청이 503 으로 정직하게 실패하는 것으로
    충분하고, 그것 때문에 조회까지 멈추는(파드를 빼는) 것은 사용자에게 더 나쁘다.

    실패는 _PROBE_RETRY_SECONDS 뒤에 다시 시도한다. 인프라가 역할을 고쳐 붙이면
    파드를 재시작하지 않아도 Ready 로 돌아온다.

    **S3 프로브는 스레드로 넘긴다.** boto3 는 동기 라이브러리라 이 코루틴에서 직접
    부르면 그동안 이벤트 루프가 멈춘다 — 위 타임아웃을 걸어도 실패 한 번에 최악 10초
    이고, 실패는 60초마다 반복되므로 S3 가 안 붙는 내내 다른 요청까지 주기적으로
    얼어붙는다. readiness 하나 때문에 조회가 멈추면 앞뒤가 바뀐다.
    """
    global _probe_ok, _probe_error, _probe_at, _probe_running

    if S3_BUCKET:
        if _probe_ok:
            return None

        now = time.monotonic()
        if _probe_error is not None and now - _probe_at < _PROBE_RETRY_SECONDS:
            return _probe_error

        if _probe_running:
            # 다른 /ready 요청이 이미 프로브 중이다. 기다리지 않고 마지막으로 아는
            # 상태를 돌려준다 — readiness 는 빨리 답하는 편이 낫고, 아직 한 번도
            # 확인하지 못했다면 "아직 준비되지 않았다"가 정직한 답이다.
            return _probe_error or "ProbeInProgress"

        _probe_running = True
        try:
            _probe_error = await asyncio.to_thread(_probe_s3)
        finally:
            _probe_running = False

        _probe_at = time.monotonic()
        _probe_ok = _probe_error is None

        if _probe_ok:
            logger.info("S3 저장소 확인: s3://%s 에 쓰기·삭제 가능", S3_BUCKET)
        else:
            logger.error(
                "S3 저장소 확인 실패: s3://%s (%s) — IAM 역할(PutObject/DeleteObject), "
                "버킷 이름, 리전을 확인하세요. %d초 뒤 다시 시도합니다.",
                S3_BUCKET,
                _probe_error,
                _PROBE_RETRY_SECONDS,
            )

        return _probe_error

    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        probe = UPLOAD_DIR / f".readycheck-{secrets.token_hex(8)}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        return type(exc).__name__

    return None


def public_url(object_name: str | None) -> str | None:
    """저장 이름을 화면이 쓸 URL로 바꾼다. S3 모드는 절대 주소, 로컬 모드는 /uploads/ 상대 주소."""
    if not object_name:
        return None

    if S3_BUCKET:
        return f"{S3_PUBLIC_BASE}/{object_name}"

    return f"/uploads/{object_name}"


def object_name_from_url(url: str | None) -> str | None:
    """
    public_url의 역함수 — 화면용 URL에서 저장 이름을 되찾는다.

    **우리가 만든 주소일 때만** 이름을 돌려주고, 아니면 None이다. CSV로 등록된
    외부 이미지 주소(수집처 CDN 등)는 남의 파일이므로 None을 받아 지우지 않게 된다.

    이 함수가 필요한 이유: DB의 image_url에는 public_url()의 결과가 담기는데,
    로컬 모드는 "/uploads/...", S3 모드는 "https://버킷.../..."라 모드마다 모양이
    다르다. 호출부가 "/uploads/" 접두어를 직접 벗기면 S3 모드에서 조용히 깨진다 —
    그 판단을 저장 모듈 안으로 가져온 것이다.
    """
    if not url:
        return None

    if url.startswith("/uploads/"):
        return url.removeprefix("/uploads/")

    if S3_PUBLIC_BASE and url.startswith(S3_PUBLIC_BASE + "/"):
        return url.removeprefix(S3_PUBLIC_BASE + "/")

    return None


def delete_image(object_name: str) -> None:
    """
    이미지를 지운다. 이미 없으면 조용히 넘어간다.

    파일이 없다는 것은 대개 이전 삭제가 성공했다는 뜻이라, 그것을 오류로 올리면
    재시도가 영영 실패한다. S3 delete_object는 원래 없는 키에도 성공을 돌려주므로
    같은 의미가 된다. 삭제 실패는 로그만 남긴다 — 고아 파일 하나가 요청 실패보다 싸다.
    """
    if S3_BUCKET:
        try:
            _get_s3().delete_object(Bucket=S3_BUCKET, Key=object_name)
        except Exception as exc:  # noqa: BLE001 — 삭제는 어떤 실패든 요청을 막지 않는다
            logger.warning("S3 삭제 실패: %s (%s)", object_name, type(exc).__name__)
        return

    try:
        resolve_upload_path(object_name).unlink(missing_ok=True)
    except ValueError:
        # 경로가 루트를 벗어난 값이면 우리가 만든 파일이 아니다. 지우지 않는다.
        return
