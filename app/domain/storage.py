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
"""

import logging
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from app.config import UPLOAD_DIR

logger = logging.getLogger(__name__)

# S3 버킷 이름. 비어 있으면 로컬 파일 모드다.
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()

# 화면이 참조할 공개 주소의 앞부분. CloudFront를 붙이면 그 도메인을 준다.
# 비워두면 버킷 기본 주소로 만든다 — 동작은 하지만 리전 리다이렉트를 탈 수 있어
# 운영에서는 명시하는 것을 권장한다.
S3_PUBLIC_BASE = (
    os.getenv("S3_PUBLIC_BASE", "").strip().rstrip("/")
    or (f"https://{S3_BUCKET}.s3.amazonaws.com" if S3_BUCKET else "")
)

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
        except ImportError as exc:
            raise RuntimeError(
                "S3_BUCKET이 설정됐지만 boto3가 없습니다. 'uv add boto3'로 설치하세요."
            ) from exc

        _s3 = boto3.client("s3")

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
        _get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=object_name,
            Body=data,
            ContentType=_CONTENT_TYPES.get(extension, "application/octet-stream"),
            # 이름이 난수라 내용이 바뀔 일이 없다 — 브라우저·CDN이 마음껏 캐시해도 된다.
            CacheControl="public, max-age=31536000, immutable",
        )
        logger.info("S3 업로드: s3://%s/%s (%d바이트)", S3_BUCKET, object_name, len(data))
    else:
        path = resolve_upload_path(object_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    return object_name


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
