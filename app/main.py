# app/main.py

"""
당근마켓 크롤링 결과(CSV)를 조회용 REST API로 제공하는 FastAPI 앱.
DB 없이 CSV를 메모리에 캐싱해서 서빙하는 단순 버전. (uv init 기본 구조 그대로,
app/ 패키지 없이 루트에 파일들을 평평하게 둔 버전)

실행: uv run uvicorn main:app --reload
문서(Swagger UI): http://127.0.0.1:8000/docs
문서(ReDoc):      http://127.0.0.1:8000/redoc
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.crawler.scheduler import crawler_loop
from app.routers.items import router as items_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    crawler_task = asyncio.create_task(
        crawler_loop()
    )

    yield

    crawler_task.cancel()

    try:
        await crawler_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="CloudeDX API",
    version="0.2.0",
    lifespan=lifespan,
)


app.include_router(
    items_router,
    prefix="/api",
)


@app.get("/")
def root():
    return {
        "message": "CloudeDX API",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }