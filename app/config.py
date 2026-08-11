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

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    """숫자 환경변수를 읽는다. 값이 비었거나 숫자가 아니면 기본값을 쓴다."""
    raw = os.getenv(name, "").strip()

    try:
        return int(raw) if raw else default
    except ValueError:
        print(f"[config] {name}={raw!r} 를 숫자로 읽을 수 없어 기본값 {default} 을 씁니다.")
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()

    if not raw:
        return default

    return raw in ("1", "true", "yes", "on")


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

# ---------------------------------------------------------------------------
# 크롤러
# ---------------------------------------------------------------------------

# 백엔드 프로세스가 크롤러를 함께 돌릴지 여부. 크롤러를 별도 컨테이너로 분리해서
# 운영할 때는 false로 두고, app/crawler/__main__.py 를 따로 띄운다.
ENABLE_CRAWLER = _bool_env("ENABLE_CRAWLER", True)

# 수집 주기(분). 사이트 부하와 봇 감지를 감안하면 너무 짧게 잡지 않는 게 좋다.
CRAWL_INTERVAL_MINUTES = _int_env("CRAWL_INTERVAL_MINUTES", 30)

# 라운드가 통째로 실패했을 때 다음 시도까지의 대기(분). 정상 주기보다 짧게 잡아,
# 일시적인 문제로 실패했을 때 주기 전체를 버리지 않게 한다.
CRAWL_RETRY_MINUTES = _int_env("CRAWL_RETRY_MINUTES", 5)

# 스케줄 실행에서는 브랜드 수만큼 곱해지니 CLI 기본값(5)보다 페이지 수를 줄인다.
JOONGNA_PAGES_PER_BRAND = _int_env("JOONGNA_PAGES_PER_BRAND", 3)

# 'running'으로 남은 수집 기록을 죽은 것으로 볼 때까지의 시간(분).
# 크롤러가 SIGKILL이나 전원 차단으로 죽으면 종료 시각을 못 남긴다. 그 기록을 그대로
# 믿으면 /api/meta가 영원히 "수집 중"이라고 답한다. 한 라운드가 정상적으로 걸리는
# 시간(수 분)보다 넉넉히 크게 잡되, 무한정 기다리지는 않는 값이어야 한다.
CRAWL_RUN_TIMEOUT_MINUTES = _int_env("CRAWL_RUN_TIMEOUT_MINUTES", 60)

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