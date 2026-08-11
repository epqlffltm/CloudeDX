#app/crawler/scheduler.py

"""
크롤링 자동화.
당근마켓/중고나라 모두 Playwright 기반 비동기 크롤러로 통일했기 때문에,
더 이상 asyncio.to_thread 없이 순서대로 await하면 된다.

브랜드(LUXURY_BRANDS)를 사이트당 하나씩 순서대로 검색해서 한 JSON 파일에 합쳐 저장한다.
브랜드 수만큼 검색 횟수가 늘어나므로 한 라운드 전체 소요 시간도 그만큼 길어진다
(현재 4개 브랜드 x 2개 사이트 = 검색 8회, 정상적인 네트워크 환경에서 수 분 단위 소요 예상).
"""

import asyncio
from pathlib import Path

from app.crawler.base import save_json
from app.crawler.brands import LUXURY_BRANDS
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler
from app.db.repository import upsert_items

CRAWL_INTERVAL_SECONDS = 30 * 60  # 30분

# 스케줄 실행에서는 브랜드 수만큼 곱해지니 CLI 기본값(5)보다 페이지 수를 줄여 소요 시간을 관리한다.
JOONGNA_PAGES_PER_BRAND = 3


async def crawl_daangn_once() -> None:
    print("[crawler] 당근마켓 자동 크롤링 시작")

    all_items = []
    for brand in LUXURY_BRANDS:
        crawler = DaangnCrawler(
            DaangnCrawlerConfig(
                brand=brand,
                headless=True,
                scroll_count=6,
            )
        )
        try:
            items = await crawler.crawl()
            all_items.extend(items)
            print(f"[crawler] 당근마켓 '{brand}' {len(items)}건")
        except Exception as exc:
            print(f"[crawler] 당근마켓 '{brand}' 크롤링 실패: {exc}")

    save_json(all_items, Path("data/crawled_items.json"))
    await upsert_items(all_items)

    print(f"[crawler] 당근마켓 자동 크롤링 완료: 총 {len(all_items)}건")


async def crawl_joongna_once() -> None:
    print("[crawler] 중고나라 자동 크롤링 시작")

    all_items = []
    for brand in LUXURY_BRANDS:
        crawler = JoongnaCrawler(
            JoongnaCrawlerConfig(
                brand=brand,
                headless=True,
                max_pages=JOONGNA_PAGES_PER_BRAND,
            )
        )
        try:
            items = await crawler.crawl()
            all_items.extend(items)
            print(f"[crawler] 중고나라 '{brand}' {len(items)}건")
        except Exception as exc:
            print(f"[crawler] 중고나라 '{brand}' 크롤링 실패: {exc}")

    save_json(all_items, Path("data/joongna_crawled_items.json"))
    await upsert_items(all_items)

    print(f"[crawler] 중고나라 자동 크롤링 완료: 총 {len(all_items)}건")


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
