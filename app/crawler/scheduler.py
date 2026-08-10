#app/crawler/scheduler.py

"""
크롤링 자동화.
당근마켓/중고나라 모두 Playwright 기반 비동기 크롤러로 통일했기 때문에,
더 이상 asyncio.to_thread 없이 순서대로 await하면 된다.
"""

import asyncio
from pathlib import Path

from app.crawler.base import save_json
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler

CRAWL_INTERVAL_SECONDS = 30 * 60  # 30분


async def crawl_daangn_once() -> None:
    print("[crawler] 당근마켓 자동 크롤링 시작")

    crawler = DaangnCrawler(
        DaangnCrawlerConfig(
            query="아이폰",
            headless=True,
            scroll_count=6,
        )
    )

    items = await crawler.crawl()

    save_json(items, Path("data/crawled_items.json"))

    print(f"[crawler] 당근마켓 자동 크롤링 완료: {len(items)}건")


async def crawl_joongna_once() -> None:
    print("[crawler] 중고나라 자동 크롤링 시작")

    crawler = JoongnaCrawler(
        JoongnaCrawlerConfig(
            keyword="구찌",
            headless=True,
            max_pages=5,
        )
    )

    items = await crawler.crawl()

    save_json(items, Path("data/joongna_crawled_items.json"))

    print(f"[crawler] 중고나라 자동 크롤링 완료: {len(items)}건")


# 순서대로 실행할 크롤링 작업 목록. 사이트를 추가하고 싶으면 여기에 함수 하나만 더 넣으면 된다.
CRAWL_JOBS = (crawl_daangn_once, crawl_joongna_once)


async def run_crawl_round() -> None:
    """등록된 크롤링 작업을 순서대로 한 바퀴 실행. 하나가 실패해도 나머지는 계속 진행한다."""
    for job in CRAWL_JOBS:
        try:
            await job()
        except Exception as exc:
            print(f"[crawler] {job.__name__} 실패: {exc}")


async def crawler_loop() -> None:
    """
    30분마다 반복 실행하는 백그라운드 루프.
    최초 1회는 main.py의 lifespan에서 run_crawl_round()로 먼저(서버 시작을 막으면서)
    실행하기 때문에, 여기서는 sleep을 먼저 하고 그 다음부터 반복한다.
    """
    while True:
        await asyncio.sleep(CRAWL_INTERVAL_SECONDS)
        await run_crawl_round()
