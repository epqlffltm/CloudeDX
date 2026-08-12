# app/main.py

"""
당근마켓/중고나라 크롤링 결과를 게시판과 JSON API로 제공하는 FastAPI 앱.

파이프라인은 하나다: 크롤러가 수집 -> DB(items 테이블)에 upsert -> 그 DB를 서빙.
서빙 경로는 이렇게 나뉜다.
    /health, /ready     운영용 상태 확인 (app/routers/health.py의 설명 참고)
    /board              Jinja2로 그린 게시판 화면 (목록 -> 제목 클릭 -> 상세)
    /api/crawled-items  같은 데이터를 주는 JSON API
    /api/meta           필터 선택지와 수집 현황
조회 경로는 모두 app.db.repository를 통하므로 필터/정렬 동작이 갈라지지 않는다.

크롤러 임포트에 대해:
    이 모듈은 app.crawler.scheduler를 **모듈 최상단에서 임포트하지 않는다.**
    scheduler는 Playwright를 끌고 오는데, 백엔드 이미지에는 Playwright도 Chromium도
    없기 때문이다(Dockerfile.backend 참고). ENABLE_CRAWLER가 켜져 있을 때만 lifespan
    안에서 지연 임포트한다.

    로컬 개발에서는 기본값이 true라 예전처럼 한 프로세스에서 다 돌아간다. 컨테이너로
    분리해 운영할 때는 백엔드를 false로 두고 `python -m app.crawler`를 따로 띄운다.

실행 (프로젝트 루트에서):
    docker compose up -d
    uv run alembic upgrade head    # 스키마 반영. 모델을 고쳤다면 반드시 먼저 실행한다
    uv run uvicorn app.main:app
게시판:           http://127.0.0.1:8000/board
문서(Swagger UI): http://127.0.0.1:8000/docs

서버 시작에 대해:
    DB 연결만 확인되면 바로 요청을 받는다. 테이블 생성/변경은 하지 않으므로,
    스키마가 최신이 아니면 서버는 뜨지만 쿼리에서 터진다 — alembic upgrade head를
    먼저 돌려야 한다. 마이그레이션을 앱 시작 시 자동 실행하지 않는 이유는, 인스턴스를
    여러 개 띄우면 동시에 같은 마이그레이션을 돌리려 들기 때문이다. 배포에서는
    별도 일회성 태스크에서 한 번만 실행한다(compose의 migrate 서비스).

Windows 참고:
    Windows에서 --reload를 쓰면 uvicorn이 "reloader process"와 별도의 "server process"를
    띄우는데, 그 server process가 자기 이벤트 루프를 만든 뒤에야 이 파일이 로드된다. 그래서
    아래 ProactorEventLoopPolicy 설정은 이미 만들어진 루프에는 적용이 안 되고, Playwright가
    브라우저를 서브프로세스로 띄우려 할 때 NotImplementedError가 난다. 확실한 해결책은
    --reload 없이 돌리는 것이다. 화면/API 코드만 빠르게 고칠 땐 --reload와
    ENABLE_CRAWLER=false를 함께 쓴다.
"""

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import ALLOWED_ORIGINS, API_PREFIX, DATABASE_URL, ENABLE_CRAWLER
from app.db.engine import mask_url, wait_for_db
from app.routers.crawled import router as crawled_router
from app.routers.health import router as health_router
from app.routers.meta import router as meta_router
from app.routers.web import router as web_router

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _log_crawler_exit(task: asyncio.Task) -> None:
    """
    수집 루프가 끝났을 때 이유를 남긴다.

    create_task로 띄운 태스크는 예외가 나도 아무도 await하지 않으면 조용히 사라진다.
    루프 안에서 대부분의 예외를 잡고 있지만, 그물을 빠져나간 무언가로 태스크가 죽으면
    "서버는 멀쩡한데 수집만 영영 안 되는" 상태가 된다. 최소한 로그에는 남겨야 한다.
    """
    if task.cancelled():
        return

    exc = task.exception()

    if exc is not None:
        print(f"[crawler] 수집 루프가 예기치 않게 종료됨: {type(exc).__name__}: {exc}")


def _start_crawler() -> asyncio.Task | None:
    """
    크롤러를 백그라운드 태스크로 띄운다. Playwright가 없으면 안내만 남기고 넘어간다.

    임포트를 함수 안에서 하는 것이 핵심이다. 백엔드 이미지에는 Playwright가 설치돼
    있지 않아서, 모듈 최상단에서 임포트하면 앱이 아예 뜨지 않는다.
    """
    try:
        from app.crawler.runner import crawler_loop
        from app.crawler.scheduler import CRAWL_JOBS
    except ImportError as exc:
        print(f"[crawler] 크롤러를 시작할 수 없습니다: {exc}")
        print("[crawler] 크롤러가 필요하면 'uv sync --extra crawler' 로 설치하세요.")
        print("[crawler] 크롤러를 별도 컨테이너로 돌리는 구성이라면 정상입니다.")
        return None

    task = asyncio.create_task(crawler_loop(CRAWL_JOBS))
    task.add_done_callback(_log_crawler_exit)

    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 테이블을 만들지는 않는다 — 스키마는 Alembic이 관리한다. 여기서는 DB가 응답하는지만
    # 확인하고, 컨테이너가 아직 기동 중이면 잠깐 기다린다.
    print(f"[db] 연결 확인 중... ({mask_url(DATABASE_URL)})")
    await wait_for_db()
    print("[db] 연결 확인 완료")

    crawler_task: asyncio.Task | None = None

    if ENABLE_CRAWLER:
        # await하지 않는다 — 서버는 바로 열리고 수집은 뒤에서 돈다.
        crawler_task = _start_crawler()
    else:
        print("[crawler] ENABLE_CRAWLER=false 라서 백그라운드 크롤러를 시작하지 않음")

    yield

    if crawler_task is not None:
        crawler_task.cancel()

        try:
            await crawler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="중고 명품 가방 조회 API",
    version="0.6.0",
    description=(
        "당근마켓·중고나라에서 수집한 중고 명품 가방 매물을 조회한다. "
        "모든 목록 응답은 total/count/limit/offset/has_next를 포함한다."
    ),
    lifespan=lifespan,
)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        # 조회 전용 API라 GET만 열어둔다. 쓰기 엔드포인트가 생기면 그때 늘린다.
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    print(f"[cors] 허용 출처: {', '.join(ALLOWED_ORIGINS)}")

app.include_router(health_router)
app.include_router(web_router)
app.include_router(crawled_router, prefix=API_PREFIX)
app.include_router(meta_router, prefix=API_PREFIX)


@app.get("/", status_code=status.HTTP_307_TEMPORARY_REDIRECT, include_in_schema=False)
def root():
    """루트로 들어온 사람은 게시판으로 보낸다. 상태 확인은 /health와 /ready를 쓴다."""
    return RedirectResponse(url="/board")