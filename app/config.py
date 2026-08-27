# app/config.py

"""
환경 변수에서 읽는 설정을 한 곳에 모은다.

이 모듈이 load_dotenv()를 호출하는 유일한 곳이고, app.* 중 가장 먼저 임포트된다.
덕분에 다른 모듈은 "임포트 순서를 지켜야 .env가 읽힌다"는 제약에서 자유롭다.
예전에는 main.py 최상단에서 load_dotenv()를 부르고 그 아래 임포트에 noqa: E402를
붙여야 했는데, 린터가 정렬하면 조용히 깨지는 구조였다.

설정을 여기 모으는 두 번째 이유는 프로세스 분리다. 백엔드와 크롤러가 별도 컨테이너로
갈라지면서, 크롤러 설정값(CRAWL_INTERVAL_MINUTES)을 백엔드가 참조해야 하는 상황이
생겼다(/api/meta가 수집 주기를 내려준다). 그 값을 scheduler.py에 두면 백엔드가
scheduler를 임포트하게 되고, scheduler는 Playwright를 끌고 온다 — Playwright 없는
백엔드 이미지에서 임포트 에러가 난다. 설정만 따로 두면 그 사슬이 끊긴다.
"""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    """
    숫자 환경변수를 읽는다. 값이 비었거나 숫자가 아니면 기본값을 쓴다.

    minimum을 주면 그보다 작은 값도 기본값으로 되돌린다. 여기서 걸러내는 이유는
    잘못된 값이 한참 뒤에 엉뚱한 증상으로 나타나기 때문이다 — CRAWL_INTERVAL_MINUTES=0
    이면 크롤러가 쉬지 않고 사이트를 두드려 차단당하고, JOONGNA_PAGES_PER_BRAND=0이면
    "수집은 도는데 아무것도 안 쌓이는" 상태가 된다. 둘 다 원인을 찾기 어렵다.

    오타 하나로 컨테이너가 부팅에 실패하는 것도 곤란하므로, 예외를 올리지 않고
    경고를 남긴 뒤 기본값으로 진행한다.
    """
    raw = os.getenv(name, "").strip()

    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError:
        # 로깅 설정 전에 실행되는 모듈이라 print를 쓴다. setup_logging()이
        # app.config를 임포트하므로 여기서 로거를 쓰면 순환 참조가 된다.
        print(f"[config] {name}={raw!r} 를 숫자로 읽을 수 없어 기본값 {default} 을 씁니다.")
        return default

    if minimum is not None and value < minimum:
        print(
            f"[config] {name}={value} 는 최소값 {minimum} 보다 작아 "
            f"기본값 {default} 을 씁니다."
        )
        return default

    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()

    if not raw:
        return default

    return raw in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# 실행 환경
# ---------------------------------------------------------------------------
#
# 로컬/CI와 운영에서 규칙이 갈리는 값이 있다. 대표적으로 비밀값이다 — 로컬에서는
# .env 없이도 떠야 개발이 되고, 운영에서는 값이 없으면 아예 뜨지 않아야 한다.
#
# 그 분기를 각 값마다 따로 판단하지 않고 여기 한 곳에서 정한다. compose 배포에서는
# docker-compose.web.yml 의 `:?` 가 같은 일을 하지만, 쿠버네티스에서는 매니페스트가
# 그걸 대신해주지 않는다. 그래서 판단을 애플리케이션 안으로 들여온다.

APP_ENV = os.getenv("APP_ENV", "local").strip().lower() or "local"

IS_PRODUCTION = APP_ENV == "production"


def _secret_env(name: str, local_default: str, *, hint: str = "") -> str:
    """
    비밀값을 읽는다. 운영에서 비어 있으면 기동을 거부한다.

    로컬/CI에서는 기본값으로 조용히 진행한다. 운영에서 같은 관용을 베풀면 안 되는
    이유는 증상이 늦게 나타나기 때문이다 — SESSION_SECRET 이 파드마다 다르면
    "로그인이 됐다 안 됐다 하는" 버그로 보이고, 파드 3개에 흩어져 있으면 재현조차
    어렵다. 기본 비밀번호로 뜬 서비스는 아예 아무 증상도 없다.

    RuntimeError 를 여기서 올리면 프로세스가 임포트 단계에서 죽는다. 쿠버네티스는
    CrashLoopBackOff 로 보여주고 로그에 이유가 남는다 — 잘못된 설정으로 트래픽을
    받는 것보다 낫다.
    """
    raw = os.getenv(name, "").strip()

    if raw:
        return raw

    if IS_PRODUCTION:
        raise RuntimeError(
            f"APP_ENV=production 인데 {name} 이 비어 있습니다. "
            f"기동을 중단합니다.{' ' + hint if hint else ''}"
        )

    return local_default


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

# localhost 대신 127.0.0.1을 명시한다. Windows + Docker Desktop 조합에서 localhost가
# IPv6(::1)로 먼저 풀리는데 포트 포워딩이 IPv4만 열려 있어 연결이 거부되는 경우가 있다.
# 컨테이너 안에서 돌 때는 compose가 DATABASE_URL로 host를 'db'로 덮어쓴다.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx",
)

# 읽기 전용 접속 주소(RDS 읽기 복제본).
#
# 비워두면 DATABASE_URL 로 떨어진다 — 로컬과 CI에는 DB가 하나뿐이고, 그 환경에서
# 읽기 경로가 따로 노는 것은 검증 가치가 없다. 두 값이 같으면 엔진도 새로 만들지
# 않고 쓰기 엔진을 그대로 재사용한다(app/db/engine.py). 커넥션 풀이 두 벌 생기는
# 것을 막기 위해서다.
DATABASE_RO_URL = os.getenv("DATABASE_RO_URL", "").strip() or DATABASE_URL

# 읽기 복제본 접속에 실패했을 때, 다시 시도하기까지 쓰기 엔진으로 보낼 시간(초).
#
# 복제본 장애는 요청 단위가 아니라 분 단위로 지속되는 사건이다. 매 요청마다 죽은
# 복제본에 붙어보고 10초(connect timeout)를 버리면 폴백이 있으나 마나 한 상태가
# 된다. 한 번 실패하면 이 시간 동안은 시도 자체를 건너뛴다.
#
# 짧게 잡으면 복제본이 돌아왔을 때 빨리 복귀하고, 길게 잡으면 장애 중 낭비가 줄어든다.
# 30초면 복제본 재기동(수 분)에 비해 충분히 짧고, 요청당 비용도 거의 없다.
READ_FALLBACK_COOLDOWN_SECONDS = _int_env("READ_FALLBACK_COOLDOWN_SECONDS", 30, minimum=1)

# ---------------------------------------------------------------------------
# 크롤러
# ---------------------------------------------------------------------------

# 백엔드 프로세스가 크롤러를 함께 돌릴지 여부. 크롤러를 별도 컨테이너로 분리해서
# 운영할 때는 false로 두고, app/crawler/__main__.py 를 따로 띄운다.
ENABLE_CRAWLER = _bool_env("ENABLE_CRAWLER", True)

# 수집 주기(분). 사이트 부하와 봇 감지를 감안하면 너무 짧게 잡지 않는 게 좋다.
CRAWL_INTERVAL_MINUTES = _int_env("CRAWL_INTERVAL_MINUTES", 30, minimum=1)

# 라운드가 통째로 실패했을 때 다음 시도까지의 대기(분). 정상 주기보다 짧게 잡아,
# 일시적인 문제로 실패했을 때 주기 전체를 버리지 않게 한다.
CRAWL_RETRY_MINUTES = _int_env("CRAWL_RETRY_MINUTES", 5, minimum=1)

# 스케줄 실행에서는 브랜드 수만큼 곱해지니 CLI 기본값(5)보다 페이지 수를 줄인다.
JOONGNA_PAGES_PER_BRAND = _int_env("JOONGNA_PAGES_PER_BRAND", 3, minimum=1)

# 번개장터 검색 잡당 API 페이지 수. 세 수집처 중 유일하게 브라우저가 없어
# 페이지당 비용이 제일 싸다 — 그래도 상대 서버 예절은 같다.
BUNJANG_PAGES_PER_JOB = _int_env("BUNJANG_PAGES_PER_JOB", 3, minimum=1)

# 'running'으로 남은 수집 기록을 죽은 것으로 볼 때까지의 시간(분).
# 크롤러가 SIGKILL이나 전원 차단으로 죽으면 종료 시각을 못 남긴다. 그 기록을 그대로
# 믿으면 /api/meta가 영원히 "수집 중"이라고 답한다. 한 라운드가 정상적으로 걸리는
# 시간(수 분)보다 넉넉히 크게 잡되, 무한정 기다리지는 않는 값이어야 한다.
CRAWL_RUN_TIMEOUT_MINUTES = _int_env("CRAWL_RUN_TIMEOUT_MINUTES", 60, minimum=1)

# 몇 번 연속으로 발견되지 않으면 비활성으로 볼지.
# 한 라운드 안 보였다고 판단하면 오탐이 잦다 — 사이트가 잠깐 느렸거나 검색 결과 순서가
# 흔들렸을 수 있다. 30분 주기 기준 3회면 1시간 30분이고, 실제 판매완료는 그 안에 반영된다.
MISSING_THRESHOLD = _int_env("MISSING_THRESHOLD", 3, minimum=1)

# ---------------------------------------------------------------------------
# 실시간 검색 (app/routers/live.py)
# ---------------------------------------------------------------------------

# 실시간 조회에서 볼 페이지 수.
#
# 스케줄 수집은 3페이지를 보지만 여기는 1페이지가 기본이다. 응답 시간이 곧 사용자
# 경험이고, 최신 매물은 1페이지에 몰려 있다. 페이지를 늘리면 페이지 간 대기까지
# 곱해져서 체감이 빠르게 나빠진다.
LIVE_SEARCH_MAX_PAGES = _int_env("LIVE_SEARCH_MAX_PAGES", 1, minimum=1)

# 실시간 조회 전체에 거는 시간 제한(초).
#
# 이 시간을 넘기면 포기하고 status=failed로 돌아간다. 화면은 이미 DB 결과를 보여주고
# 있으므로 사용자가 잃는 것은 "몇 초 더 신선했을 매물"뿐이다. 반대로 제한이 없으면
# 상대 사이트가 느릴 때 요청이 매달려 워커를 붙잡는다.
LIVE_SEARCH_TIMEOUT_SECONDS = _int_env("LIVE_SEARCH_TIMEOUT_SECONDS", 8, minimum=1)

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

# 프론트엔드를 별도 개발 서버(Vite 5173 등)로 띄우면 브라우저가 다른 출처로 보고
# 요청을 막는다. 비워두면 CORS 미들웨어를 아예 붙이지 않는다.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# API 경로 접두어. 화면(/board)과 분리해 두면 리버스 프록시에서 /api만 백엔드로
# 넘기는 구성이 쉬워지고, 나중에 /api/v2를 병행하는 것도 가능해진다.
API_PREFIX = "/api"


# ---------------------------------------------------------------------------
# 로깅
# ---------------------------------------------------------------------------

# DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

# text = 사람이 읽는 형식(로컬), json = 한 줄 JSON(배포).
# 로그 수집기가 필드 단위로 질의하려면 json이 필요하다.
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").strip().lower() or "text"

# ---------------------------------------------------------------------------
# 인증 (시연용)
# ---------------------------------------------------------------------------
#
# 계정이 둘뿐이고 회원가입이 없어서 DB 테이블 대신 설정에 둔다. 자세한 이유는
# app/auth.py의 모듈 설명을 참고한다.
#
# 로컬에서는 .env 없이도 뜨도록 기본값을 둔다. 운영(APP_ENV=production)에서는
# 비밀값이 비어 있으면 _secret_env 가 기동을 거부한다.

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = _secret_env(
    "ADMIN_PASSWORD",
    "admin1234",
    hint="Secrets Manager 에서 주입되는 값입니다.",
)

CLIENT_USERNAME = os.getenv("CLIENT_USERNAME", "client").strip() or "client"
CLIENT_PASSWORD = _secret_env(
    "CLIENT_PASSWORD",
    "client1234",
    hint="Secrets Manager 에서 주입되는 값입니다.",
)

# 세션 쿠키 서명 키.
#
# 지정하지 않으면 프로세스마다 임의로 만든다. 서버를 재시작하면 기존 로그인이
# 전부 풀리고, 인스턴스를 여러 개 띄우면 서로의 쿠키를 인정하지 않는다.
# 로컬 시연에서는 그래도 되지만, 파드가 3개인 운영에서는 로그인이 사실상 동작하지
# 않는다 — 그래서 운영에서는 미설정 시 기동을 거부한다.
#     python -c "import secrets; print(secrets.token_hex(32))"
SESSION_SECRET = _secret_env(
    "SESSION_SECRET",
    secrets.token_hex(32),
    hint="파드 3개가 같은 값을 써야 합니다.",
)

# 로그인 유지 시간. 기본 12시간.
SESSION_MAX_AGE_SECONDS = _int_env("SESSION_MAX_AGE_SECONDS", 12 * 60 * 60, minimum=60)

# 세션 쿠키에 Secure 플래그를 붙일지 여부.
#
# 붙이면 브라우저가 HTTPS 연결에서만 쿠키를 보낸다. 로컬은 http://localhost 라
# 켜면 로그인이 아예 안 되므로 기본값을 APP_ENV 에 맡긴다.
#
# request.url.scheme 으로 판단하지 않는 이유: TLS 는 ALB/CloudFront 에서 끝나고
# 그 뒤 구간은 평문 HTTP 다. 앱이 보는 scheme 은 --proxy-headers 를 켜도
# X-Forwarded-Proto 에 의존하는데, 그 헤더는 신뢰 대역 설정이 어긋나면 조용히
# 틀린 값이 된다. 쿠키 보안 속성을 그런 값에 걸어두고 싶지 않다.
COOKIE_SECURE = _bool_env("COOKIE_SECURE", IS_PRODUCTION)

# CSV 업로드 한 번에 받을 최대 바이트. 기본 5MB.
# 본문을 읽는 도중에 이 선을 넘으면 그 자리에서 끊는다 — 다 읽은 뒤에 재고 거절하면
# 막으려던 파일이 이미 메모리에 올라와 있다(app/routers/uploads.py 참고).
MAX_UPLOAD_BYTES = _int_env("MAX_UPLOAD_BYTES", 5 * 1024 * 1024, minimum=1024)

# 쓰기 경로가 DB를 붙잡고 있을 수 있는 최대 시간(초).
#
# 주 DB가 페일오버하는 동안 업로드 요청은 어차피 성공하지 못한다. 제한이 없으면
# 커넥션 타임아웃까지 매달려 워커를 붙잡고, 그 사이 살아 있는 조회 경로까지
# 대기가 생긴다. 빨리 503으로 끊고 다시 시도하게 하는 편이 낫다.
#
# connect timeout(10초)보다는 넉넉해야 한다 — 그보다 짧게 잡으면 정상적인
# 재연결까지 잘라내서, DB가 멀쩡한데도 업로드가 실패한다.
WRITE_TIMEOUT_SECONDS = _int_env("WRITE_TIMEOUT_SECONDS", 15, minimum=1)
