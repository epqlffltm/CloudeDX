# app/main.py

"""
당근마켓/중고나라 크롤링 결과를 게시판과 JSON API로 제공하는 FastAPI 앱.

파이프라인은 하나다: 크롤러가 수집 -> DB(items 테이블)에 upsert -> 그 DB를 서빙.
서빙 경로는 이렇게 나뉜다.
    /health, /ready     운영용 상태 확인 (app/routers/health.py의 설명 참고)
    /metrics            Prometheus 지표 (클러스터 내부 수집용)
    /board              Jinja2로 그린 게시판 화면 (목록 -> 제목 클릭 -> 상세)
    /api/crawled-items  같은 데이터를 주는 JSON API
    /api/meta           필터 선택지와 수집 현황
    /api/products       프론트엔드(ReLuxe)가 소비하는 상품 모양
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
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import (
    ALLOWED_ORIGINS,
    API_PREFIX,
    DATABASE_RO_URL,
    DATABASE_URL,
    ENABLE_CRAWLER,
)
from app.db.engine import engine, mask_url, read_engine, wait_for_db
from app.logging_config import setup_logging
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.crawled import router as crawled_router
from app.routers.health import router as health_router
from app.routers.meta import router as meta_router
from app.routers.products import router as products_router
from app.routers.uploads import router as uploads_router
from app.routers.web import router as web_router
from app.version import __version__

logger = logging.getLogger(__name__)

# uvicorn이 이 모듈을 임포트한 직후 실행된다. 라우터가 로거를 얻기 전에 끝나야
# 첫 로그부터 형식이 맞는다.
setup_logging()

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
        logger.warning("수집 루프가 예기치 않게 종료됨: %s: %s", type(exc).__name__, exc)


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
        logger.warning("크롤러를 시작할 수 없습니다: %s", exc)
        logger.info("크롤러가 필요하면 'uv sync --extra crawler' 로 설치하세요.")
        logger.info("크롤러를 별도 컨테이너로 돌리는 구성이라면 정상입니다.")
        return None

    task = asyncio.create_task(crawler_loop(CRAWL_JOBS))
    task.add_done_callback(_log_crawler_exit)

    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 테이블을 만들지는 않는다 — 스키마는 Alembic이 관리한다. 여기서는 DB가 응답하는지만
    # 확인하고, 컨테이너가 아직 기동 중이면 잠깐 기다린다.
    #
    # 기동을 막는 기준은 **읽기 경로**다. 조회가 이 서비스 트래픽의 대부분이고,
    # 그것조차 안 되는 파드는 떠 봐야 할 일이 없다.
    logger.info("연결 확인 중... (%s)", mask_url(DATABASE_RO_URL))
    await wait_for_db(read_engine)
    logger.info("연결 확인 완료")

    # 주 DB는 확인하되 기동을 막지 않는다.
    #
    # 페일오버 중에 파드가 새로 뜨는 경우가 있다 — 노드 교체, 스케일 아웃, 앞선
    # 파드의 재시작. 여기서 예외를 올리면 그 파드는 CrashLoopBackOff 로 빠지고,
    # 복제본이 멀쩡한데도 조회를 서빙하지 못한다. 읽기/쓰기를 나눠놓고 기동에서
    # 다시 묶어버리는 셈이다.
    #
    # 주 DB가 없는 상태는 /ready 의 database_write 와 업로드 요청의 실패로 드러난다.
    if read_engine is not engine:
        try:
            await wait_for_db(engine, retries=2)
        except RuntimeError:
            logger.warning(
                "주 DB에 연결하지 못했습니다 (%s). 조회는 계속하고 쓰기만 실패합니다.",
                mask_url(DATABASE_URL),
            )

    crawler_task: asyncio.Task | None = None

    if ENABLE_CRAWLER:
        # await하지 않는다 — 서버는 바로 열리고 수집은 뒤에서 돈다.
        crawler_task = _start_crawler()
    else:
        logger.info("ENABLE_CRAWLER=false 라서 백그라운드 크롤러를 시작하지 않음")

    yield

    if crawler_task is not None:
        crawler_task.cancel()

        try:
            await crawler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="중고 명품 가방 조회 API",
    version=__version__,
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
    logger.info("허용 출처: %s", ', '.join(ALLOWED_ORIGINS))

app.include_router(health_router)
app.include_router(web_router)
app.include_router(crawled_router, prefix=API_PREFIX)
app.include_router(meta_router, prefix=API_PREFIX)
app.include_router(products_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(uploads_router, prefix=API_PREFIX)

# ---------------------------------------------------------------------------
# Prometheus 지표 — /metrics
#
# 노드/컨테이너 지표만으로는 사용자 관점을 볼 수 없다. 노드 CPU 그래프는 "DB가
# 죽는 동안에도 조회는 200을 뱉었다"를 보여주지 못한다. 요청 수·지연·상태 코드를
# 경로별로 남겨야 그 문장이 그래프가 된다.
#
# 여기서 붙이는 이유는 등록 순서 때문이다. 아래 StaticFiles mount 가 "/" 를 통째로
# 가져가므로, /metrics 는 반드시 그 앞에서 등록돼야 한다.
#
# 경로 라벨은 raw path 가 아니라 라우트 템플릿으로 나간다(/board/{item_id}).
# raw path 로 두면 매물 id 하나마다 시계열이 하나씩 생겨서 카디널리티가 터진다.
#
# 읽기/쓰기 구분은 여기가 아니라 app/db/engine.py 의 cloudedx_db_session_total 이
# 담당한다. HTTP 지표는 "요청이 성공했는가"만 알고, 그 요청이 복제본 덕에 성공한
# 것인지는 모르기 때문이다.
#
# 주의 — 이 엔드포인트는 앱과 같은 포트(8000)에 붙는다. Ingress 가 "/" 를 백엔드로
# 보내는 이상 외부에서도 열린다. 차단은 Ingress 규칙에서 해야 하고, ServiceMonitor
# 설정만으로는 막히지 않는다.
# ---------------------------------------------------------------------------
Instrumentator(
    # 헬스체크는 몇 초마다 오므로 지표에 섞이면 실제 트래픽 그래프가 묻힌다.
    excluded_handlers=["/metrics", "/health", "/ready"],
).instrument(app).expose(app, include_in_schema=False)

# ---------------------------------------------------------------------------
# 웹 화면 서빙. 프론트(web/)를 API와 같은 출처에서 내보낸다.
#
# 이 mount 하나로 CORS가 소멸한다 — 브라우저 입장에서 화면과 API가 한 주소라
# 교차 출처 자체가 발생하지 않는다. ALLOWED_ORIGINS는 프론트를 다른 곳에서
# 호스팅하는 경우에만 쓰는 선택지가 됐다.
#
# 등록 순서가 곧 우선순위다: /api·/board·/docs 같은 등록된 라우트가 먼저
# 매칭되고, 남는 경로만 이 mount로 떨어진다. 그래서 mount는 반드시 맨 뒤다.
# html=True는 "/" 요청에 index.html을 돌려준다 — 예전의 /board 리다이렉트를
# 대체한다. 이제 루트가 곧 서비스 화면이고, 게시판은 /board 직행으로 남는다.
# ---------------------------------------------------------------------------
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
    logger.info("웹 화면 서빙: %s", _WEB_DIR)
else:
    logger.info("web/ 디렉토리가 없어 API만 서빙한다")