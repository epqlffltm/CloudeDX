# app/main.py

"""
당근마켓/중고나라 크롤링 결과를 게시판과 JSON API로 제공하는 FastAPI 앱.

파이프라인은 하나다: 크롤러가 수집 -> DB(items 테이블)에 upsert -> 그 DB를 서빙.
서빙 경로만 둘로 나뉜다.
    /board              Jinja2로 그린 게시판 화면 (목록 -> 제목 클릭 -> 상세)
    /api/crawled-items  같은 데이터를 주는 JSON API
    /api/meta           프론트가 필터 선택지를 채우는 데 쓰는 값들
셋 다 app.db.repository를 통해 조회하므로 필터/정렬 동작이 갈라지지 않는다.

게시판은 시연용이고, 프론트엔드를 붙이면 /api만 쓰면 된다. 그때 app/routers/web.py와
app/templates/를 통째로 걷어내도 API는 그대로 남는다.

실행 (프로젝트 루트에서, Postgres가 떠 있어야 함 — docker compose up -d):
    uv run uvicorn app.main:app
게시판:           http://127.0.0.1:8000/board
문서(Swagger UI): http://127.0.0.1:8000/docs
문서(ReDoc):      http://127.0.0.1:8000/redoc

환경변수에 대해:
    프로젝트 루트의 .env 파일을 읽는다 (.env.example 참고). load_dotenv()는 아래에서
    app.* 모듈보다 먼저 호출되는데, app.db.engine이 모듈을 읽어들이는 시점에
    os.getenv로 DATABASE_URL을 확정하기 때문이다. 순서가 바뀌면 .env를 읽어도
    이미 늦어서 기본값이 박힌다. 그래서 아래 임포트에 noqa: E402가 붙어 있다.

첫 크롤링을 기다리는 것에 대해:
    ENABLE_CRAWLER=true(기본값)면 서버가 요청을 받기 시작하기 전에 당근마켓+중고나라
    크롤링을 한 바퀴 다 돌린다. 브랜드 4개 x 사이트 2개라 수 분 걸릴 수 있다.
    ENABLE_CRAWLER=false여도 DB 테이블 준비는 항상 하기 때문에, 이전에 크롤링해둔
    데이터가 있으면 게시판과 API 모두 정상적으로 조회된다.

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

from app.crawler.scheduler import crawler_loop, run_crawl_round  # noqa: E402
from app.db.engine import init_db  # noqa: E402
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[db] 테이블 준비 중...")
    await init_db()

    crawler_task: asyncio.Task | None = None

    if ENABLE_CRAWLER:
        print("[crawler] 첫 크롤링을 먼저 완료한 뒤 서버를 엽니다 (당근마켓 -> 중고나라)...")
        await run_crawl_round()
        print("[crawler] 첫 크롤링 완료. 서버를 엽니다.")
        crawler_task = asyncio.create_task(crawler_loop())
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
    version="0.4.0",
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
    """프로세스가 살아있는지만 알려주는 엔드포인트 (DB 상태는 확인하지 않는다)."""
    return {"status": "ok"}