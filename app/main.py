# app/main.py

"""
당근마켓/중고나라 크롤링 결과를 조회용 REST API로 제공하는 FastAPI 앱.
서버 시작 시(lifespan) DB 테이블을 준비하고, 첫 크롤링을 먼저 끝낸 뒤에야 요청을
받기 시작한다. 이후로는 30분마다 백그라운드에서 크롤러(app.crawler)가 최신 매물을
DB(items 테이블)에 upsert한다.
/items 라우터(app.routers.items)는 CSV 스냅샷을, /crawled-items는 DB에 저장된
실제 크롤링 결과를 서빙한다.

실행 (프로젝트 루트에서, Postgres가 떠 있어야 함 — docker compose up -d):
    uv run uvicorn app.main:app --reload
문서(Swagger UI): http://127.0.0.1:8000/docs
문서(ReDoc):      http://127.0.0.1:8000/redoc

첫 크롤링을 기다리는 것에 대해:
    ENABLE_CRAWLER=true(기본값)면 서버가 요청을 받기 시작하기 전에 당근마켓+중고나라
    크롤링을 한 바퀴 다 돌린다. 브랜드 4개 x 사이트 2개라 수 분 걸릴 수 있다.
    ENABLE_CRAWLER=false여도 DB 테이블 준비는 항상 하기 때문에, 이전에 크롤링해둔
    데이터가 있으면 /crawled-items는 정상적으로 조회된다. --reload는 파일을 고칠
    때마다 프로세스를 통째로 재시작하는데, 그때마다 크롤링 대기가 매번 다시 발생하니
    API 코드만 빠르게 고칠 땐 ENABLE_CRAWLER=false로 꺼두는 걸 권장한다.

Windows 참고:
    Windows에서 --reload를 쓰면 uvicorn이 "reloader process"와 별도의 "server process"를
    띄우는데, 그 server process가 자기 이벤트 루프를 만든 뒤에야 이 파일이 로드된다. 그래서
    아래 ProactorEventLoopPolicy 설정은 이미 만들어진 루프에는 적용이 안 되고, Playwright가
    브라우저를 서브프로세스로 띄우려 할 때 NotImplementedError가 난다. 확실한 해결책은
    --reload 없이 돌리는 것이다 (uv run uvicorn app.main:app). API 코드만 빠르게 고칠 땐
    --reload + ENABLE_CRAWLER=false 조합을 쓴다.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, status

from app.crawler.scheduler import crawler_loop, run_crawl_round
from app.db.engine import init_db
from app.routers.crawled import router as crawled_router
from app.routers.items import router as items_router

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ENABLE_CRAWLER = os.getenv("ENABLE_CRAWLER", "true").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[db] 테이블 준비 중...")
    try:
        await init_db()
    except Exception as exc:
        print(f"[db] DB 연결/초기화 실패: {exc}")
        print("[db] docker compose up -d 로 Postgres가 떠 있는지, DATABASE_URL이 맞는지 확인하세요.")
        raise

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
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(items_router)
app.include_router(crawled_router)


@app.get("/", status_code=status.HTTP_200_OK)
def root():
    return {
        "message": "중고 명품 가방 조회 API",
    }
