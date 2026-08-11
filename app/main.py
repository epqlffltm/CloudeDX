# app/main.py

"""
당근마켓/중고나라 크롤링 결과를 게시판과 JSON API로 제공하는 FastAPI 앱.

파이프라인은 하나다: 크롤러가 수집 -> DB(items 테이블)에 upsert -> 그 DB를 서빙.
서빙 경로만 둘로 나뉜다.
    /board              Jinja2로 그린 게시판 화면 (목록 -> 제목 클릭 -> 상세)
    /api/crawled-items  같은 데이터를 주는 JSON API
    /api/meta           필터 선택지와 수집 현황
셋 다 app.db.repository를 통해 조회하므로 필터/정렬 동작이 갈라지지 않는다.

게시판은 시연용이고, 프론트엔드를 붙이면 /api만 쓰면 된다. 그때 app/routers/web.py와
app/templates/를 통째로 걷어내도 API는 그대로 남는다.

실행 (프로젝트 루트에서):
    docker compose up -d
    uv run alembic upgrade head    # 스키마 반영. 모델을 고쳤다면 반드시 먼저 실행한다
    uv run uvicorn app.main:app
게시판:           http://127.0.0.1:8000/board
문서(Swagger UI): http://127.0.0.1:8000/docs
문서(ReDoc):      http://127.0.0.1:8000/redoc

서버 시작에 대해:
    DB 연결만 확인되면 바로 요청을 받는다. 테이블 생성/변경은 하지 않으므로,
    스키마가 최신이 아니면 서버는 뜨지만 쿼리에서 터진다 — alembic upgrade head를
    먼저 돌려야 한다. 마이그레이션을 앱 시작 시 자동 실행하지 않는 이유는, 인스턴스를
    여러 개 띄우면 동시에 같은 마이그레이션을 돌리려 들기 때문이다. 배포에서는
    컨테이너 진입점이나 별도 태스크에서 한 번만 실행한다. 크롤링은 백그라운드 태스크로 돌기
    때문에 시작을 막지 않는다. 수집 전이라면 목록이 비어 있을 뿐 API와 화면은 정상
    응답한다. 진행 상황은 /api/meta의 crawler 항목에서 볼 수 있다.

    이 구조가 필요한 이유는 배포 환경 때문이다. ECS나 App Runner 같은 오케스트레이터는
    헬스체크가 정해진 시간 안에 응답하지 않으면 컨테이너를 죽이고 다시 띄운다. 시작 시
    수 분짜리 크롤링을 기다리면 서버가 뜨기도 전에 재시작되는 무한 루프에 빠진다.

환경변수에 대해:
    프로젝트 루트의 .env 파일을 읽는다 (.env.example 참고). load_dotenv()는 아래에서
    app.* 모듈보다 먼저 호출되는데, app.db.engine이 모듈을 읽어들이는 시점에
    os.getenv로 DATABASE_URL을 확정하기 때문이다. 순서가 바뀌면 .env를 읽어도
    이미 늦어서 기본값이 박힌다. 그래서 아래 임포트에 noqa: E402가 붙어 있다.

Windows 참고:
    Windows에서 --reload를 쓰면 uvicorn이 "reloader process"와 별도의 "server process"를
    띄우는데, 그 server process가 자기 이벤트 루프를 만든 뒤에야 이 파일이 로드된다. 그래서
    아래 ProactorEventLoopPolicy 설정은 이미 만들어진 루프에는 적용이 안 되고, Playwright가
    브라우저를 서브프로세스로 띄우려 할 때 NotImplementedError가 난다. 확실한 해결책은
    --reload 없이 돌리는 것이다 (uv run uvicorn app.main:app). 화면/API 코드만 빠르게
    고칠 땐 --reload + ENABLE_CRAWLER=false 조합을 쓴다.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# app.* 임포트보다 반드시 먼저 실행돼야 한다 (위 docstring의 "환경변수에 대해" 참고).
load_dotenv()

from app.crawler.scheduler import crawler_loop  # noqa: E402
from app.db.engine import wait_for_db  # noqa: E402
from app.routers.crawled import router as crawled_router  # noqa: E402
from app.routers.meta import router as meta_router  # noqa: E402
from app.routers.web import router as web_router  # noqa: E402

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ENABLE_CRAWLER = os.getenv("ENABLE_CRAWLER", "true").lower() == "true"

# 프론트엔드를 별도 개발 서버(Vite 5173, CRA 3000 등)로 띄우면 브라우저가 다른 출처로
# 보고 요청을 막는다. 허용할 출처를 .env의 ALLOWED_ORIGINS에 쉼표로 나열한다.
# 비워두면 CORS 미들웨어를 아예 붙이지 않는다 — 프론트가 없는 지금 상태에서 불필요하게
# 열어두지 않기 위해서다.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# API 경로 접두어. 화면(/board)과 분리해 두면 리버스 프록시에서 /api만 백엔드로
# 넘기는 구성이 쉬워지고, 나중에 /api/v2를 병행하는 것도 가능해진다.
API_PREFIX = "/api"


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 테이블을 만들지는 않는다 — 스키마는 Alembic이 관리한다. 여기서는 DB가 응답하는지만
    # 확인하고, 컨테이너가 아직 기동 중이면 잠깐 기다린다.
    print("[db] 연결 확인 중...")
    await wait_for_db()
    print("[db] 연결 확인 완료")

    crawler_task: asyncio.Task | None = None

    if ENABLE_CRAWLER:
        # await하지 않는다 — 서버는 바로 열리고 수집은 뒤에서 돈다.
        crawler_task = asyncio.create_task(crawler_loop())
        crawler_task.add_done_callback(_log_crawler_exit)
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
    version="0.5.0",
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

app.include_router(web_router)
app.include_router(crawled_router, prefix=API_PREFIX)
app.include_router(meta_router, prefix=API_PREFIX)


@app.get("/", status_code=status.HTTP_307_TEMPORARY_REDIRECT, include_in_schema=False)
def root():
    """루트로 들어온 사람은 게시판으로 보낸다. 상태 확인은 /health를 쓴다."""
    return RedirectResponse(url="/board")


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    operation_id="getHealth",
    tags=["health"],
)
def health():
    """
    프로세스가 살아있는지만 알려주는 엔드포인트.

    일부러 DB도 크롤러도 확인하지 않는다. 오케스트레이터는 이 응답을 보고 컨테이너를
    죽일지 결정하는데, DB가 잠깐 끊겼다고 앱을 재시작하는 건 상황을 악화시킨다.
    수집 현황은 /api/meta에서 본다.
    """
    return {"status": "ok"}
