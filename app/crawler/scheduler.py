# app/crawler/scheduler.py

"""
사이트별 수집 작업 정의. **여기부터 Playwright가 필요하다.**

"무엇을 어떻게 긁는지"만 다룬다. 언제 돌릴지·라운드 전체 실패를 어떻게 기록할지는
app/crawler/runner.py에 있고, 사이트 내부의 브랜드/페이지 실패 판단은
app/crawler/source_runner.py에 있다.

브랜드(LUXURY_BRANDS)를 사이트당 하나씩 순서대로 검색해서 DB에 upsert한다.
브랜드 수만큼 검색 횟수가 늘어나므로 한 라운드 소요 시간도 그만큼 길어진다
(현재 4개 브랜드 x 2개 사이트 = 검색 8회, 정상적인 환경에서 수 분 단위 소요 예상).

브랜드 하나가 실패해도 나머지는 계속한다. 하지만 한 사이트의 모든 브랜드가 예외로
실패하면 source_runner.collect_brands()가 예외를 올린다. 그래야 runner.py가
"사이트 전체 실패"와 정상적인 "검색 결과 0건"을 구분할 수 있다.

운영 수집 경로에서는 JSON 덤프를 쓰지 않는다. DB가 정본이고, 디버그 파일 쓰기 실패가
DB upsert까지 막아서는 안 되기 때문이다. JSON이 필요하면 수동 실행용 CLI에서 저장한다.
"""

from app.config import JOONGNA_PAGES_PER_BRAND
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler
from app.crawler.runner import CrawlJob
from app.crawler.source_runner import collect_brands
from app.db.repository import upsert_items
from app.domain.brands import LUXURY_BRANDS


async def crawl_daangn_once() -> int:
    """당근마켓을 브랜드별로 한 바퀴 수집하고 저장한 건수를 반환한다."""
    print("[crawler] 당근마켓 자동 크롤링 시작")

    async def crawl_brand(brand: str):
        crawler = DaangnCrawler(
            DaangnCrawlerConfig(
                brand=brand,
                headless=True,
                scroll_count=6,
            )
        )
        return await crawler.crawl()

    all_items = await collect_brands(
        source_name="당근마켓",
        brands=LUXURY_BRANDS,
        crawl_brand=crawl_brand,
    )

    saved = await upsert_items(all_items)

    print(f"[crawler] 당근마켓 자동 크롤링 완료: 총 {saved}건")

    return saved


async def crawl_joongna_once() -> int:
    """중고나라를 브랜드별로 한 바퀴 수집하고 저장한 건수를 반환한다."""
    print("[crawler] 중고나라 자동 크롤링 시작")

    async def crawl_brand(brand: str):
        crawler = JoongnaCrawler(
            JoongnaCrawlerConfig(
                brand=brand,
                headless=True,
                max_pages=JOONGNA_PAGES_PER_BRAND,
            )
        )
        return await crawler.crawl()

    all_items = await collect_brands(
        source_name="중고나라",
        brands=LUXURY_BRANDS,
        crawl_brand=crawl_brand,
    )

    saved = await upsert_items(all_items)

    print(f"[crawler] 중고나라 자동 크롤링 완료: 총 {saved}건")

    return saved


# 한 라운드에서 순서대로 실행할 작업. 사이트를 추가하려면 함수 하나를 만들어
# 여기에 넣으면 되고, 실행 규칙(주기·재시도·기록)은 손댈 필요가 없다.
CRAWL_JOBS: tuple[CrawlJob, ...] = (
    crawl_daangn_once,
    crawl_joongna_once,
)
