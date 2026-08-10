#app/crawler/scheduler.py

"""
크롤링 자동화
"""

import asyncio
from pathlib import Path

from app.crawler.config import CrawlerConfig
from app.crawler.crawler import DaangnCrawler
from app.crawler.run import save_json


CRAWL_INTERVAL_SECONDS = 30 * 60  # 30분


def crawl_once() -> None:
    print("[crawler] 자동 크롤링 시작")

    crawler = DaangnCrawler(
        CrawlerConfig(
            headless=True,
            scroll_count=6,
        )
    )

    items = crawler.crawl(
        query="아이폰",
    )

    save_json(
        items,
        Path("data/crawled_items.json"),
    )

    print(f"[crawler] 자동 크롤링 완료: {len(items)}건")


async def crawler_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(crawl_once)
        except Exception as exc:
            print(f"[crawler] 크롤링 실패: {exc}")

        await asyncio.sleep(CRAWL_INTERVAL_SECONDS)