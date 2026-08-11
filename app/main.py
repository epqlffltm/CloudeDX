# app/main.py

"""
당근마켓/중고나라 크롤링 결과를 게시판과 REST API로 제공하는 FastAPI 앱.

파이프라인은 하나다: 크롤러가 수집 -> DB(items 테이블)에 upsert -> 그 DB를 서빙.
서빙 경로만 둘로 나뉜다.
    /board          Jinja2로 그린 게시판 화면 (목록 -> 제목 클릭 -> 상세)
    /crawled-items  같은 데이터를 주는 JSON API (나중에 프론트를 붙일 자리)
둘 다 app.db.repository를 통해 조회하므로 필터/정렬 동작이 갈라지지 않는다.

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
from fastapi.responses import RedirectResponse

# app.* 임포트보다 반드시 먼저 실행돼야 한다 (위 docstring의 "환경변수에 대해" 참고).
load_dotenv()

from app.crawler.scheduler import crawler_loop, run_crawl_round  # noqa: E402
from app.db.engine import init_db  # noqa: E402
from app.routers.crawled import router as crawled_router  # noqa: E402
from app.routers.web import router as web_router  # noqa: E402

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ENABLE_CRAWLER = os.getenv("ENABLE_CRAWLER", "true").lower() == "true"


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
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(web_router)
app.include_router(crawled_router)


@app.get("/", status_code=status.HTTP_307_TEMPORARY_REDIRECT, include_in_schema=False)
def root():
    """루트로 들어온 사람은 게시판으로 보낸다. 상태 확인은 /health를 쓴다."""
    return RedirectResponse(url="/board")


@app.get("/health", status_code=status.HTTP_200_OK, tags=["health"])
def health():
    """프로세스가 살아있는지만 알려주는 엔드포인트 (DB 상태는 확인하지 않는다)."""
    return {"status": "ok"}
