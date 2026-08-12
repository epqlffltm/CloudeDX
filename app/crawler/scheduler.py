# app/crawler/scheduler.py

"""
사이트별 수집 작업 정의. **여기부터 Playwright가 필요하다.**

"무엇을 어떻게 긁는지"만 다룬다. 언제 돌릴지·실패하면 어떻게 할지 같은 실행 규칙은
app/crawler/runner.py에 있고, 이 파일은 그 규칙에 넘길 작업 목록(CRAWL_JOBS)을 만든다.

둘을 나눈 이유는 runner.py의 설명을 참고. 요약하면 실행 규칙을 브라우저 없이 테스트하고,
백엔드가 규칙만 쓰고 싶을 때 Chromium이 딸려 오지 않게 하려는 것이다.

브랜드(LUXURY_BRANDS)를 사이트당 하나씩 순서대로 검색해서 DB에 upsert한다.
브랜드 수만큼 검색 횟수가 늘어나므로 한 라운드 소요 시간도 그만큼 길어진다
(현재 4개 브랜드 x 2개 사이트 = 검색 8회, 정상적인 환경에서 수 분 단위 소요 예상).

한 브랜드가 실패해도 나머지 브랜드는 계속한다. 사이트 전체가 실패했을 때의 처리는
runner.run_crawl_round()가 맡는다.
"""

from pathlib import Path

from app.config import JOONGNA_PAGES_PER_BRAND
from app.crawler.base import save_json
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler
from app.crawler.runner import CrawlJob
from app.db.repository import upsert_items
from app.domain.brands import LUXURY_BRANDS


async def crawl_daangn_once() -> int:
    """당근마켓을 브랜드별로 한 바퀴 수집하고 저장한 건수를 반환한다."""
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
    saved = await upsert_items(all_items)

    print(f"[crawler] 당근마켓 자동 크롤링 완료: 총 {saved}건")

    return saved


async def crawl_joongna_once() -> int:
    """중고나라를 브랜드별로 한 바퀴 수집하고 저장한 건수를 반환한다."""
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
    saved = await upsert_items(all_items)

    print(f"[crawler] 중고나라 자동 크롤링 완료: 총 {saved}건")

    return saved


# 한 라운드에서 순서대로 실행할 작업. 사이트를 추가하려면 함수 하나를 만들어
# 여기에 넣으면 되고, 실행 규칙(주기·재시도·기록)은 손댈 필요가 없다.
CRAWL_JOBS: tuple[CrawlJob, ...] = (
    crawl_daangn_once,
    crawl_joongna_once,
)