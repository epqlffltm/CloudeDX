# app/crawler/scheduler.py

"""
사이트별 수집 작업 정의. **여기부터 Playwright가 필요하다.**

"무엇을 어떻게 긁는지"만 다룬다. 언제 돌릴지·라운드 전체 실패를 어떻게 기록할지는
app/crawler/runner.py에 있고, 사이트 내부의 브랜드/페이지 실패 판단은
app/crawler/source_runner.py에 있다.

검색 계획(SEARCH_PLAN)의 잡을 사이트당 하나씩 순서대로 검색해서 DB에 upsert한다.
브랜드 수만큼 검색 횟수가 늘어나므로 한 라운드 소요 시간도 그만큼 길어진다
(현재 4개 브랜드 x 2개 사이트 = 검색 8회, 정상적인 환경에서 수 분 단위 소요 예상).

브랜드 하나가 실패해도 나머지는 계속한다. 하지만 한 사이트의 모든 브랜드가 예외로
실패하면 source_runner.collect_brands()가 예외를 올린다. 그래야 runner.py가
"사이트 전체 실패"와 정상적인 "검색 결과 0건"을 구분할 수 있다.

운영 수집 경로에서는 JSON 덤프를 쓰지 않는다. DB가 정본이고, 디버그 파일 쓰기 실패가
DB upsert까지 막아서는 안 되기 때문이다. JSON이 필요하면 수동 실행용 CLI에서 저장한다.
"""

import logging

from app.config import BUNJANG_PAGES_PER_JOB, JOONGNA_PAGES_PER_BRAND
from app.crawler.bunjang.config import BunjangCrawlerConfig
from app.crawler.bunjang.crawler import BunjangCrawler
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler
from app.crawler.runner import CrawlJob
from app.crawler.source_runner import collect_jobs
from app.db.repository import sweep_missing, upsert_items
from app.domain.collection import CrawlScope, SearchJob
from app.domain.search_plan import SEARCH_PLAN
from app.domain.sources import BUNJANG, DAANGN, JOONGNA

logger = logging.getLogger(__name__)


async def _collect_and_store(
    *,
    source_name: str,
    crawl_job,
) -> tuple[int, dict[str, dict]]:
    """
    한 사이트를 브랜드별로 수집하고 저장한 뒤, 사라진 매물을 정리한다.

    두 사이트가 이 흐름을 공유한다. 수집 방식(스크롤 vs 페이지네이션)만 다르고
    저장·정리 규칙은 같아야 하기 때문이다 — 한쪽만 고치면 사이트마다 매물 생명주기가
    달라진다.

    미발견 정리는 **완전히 훑은 브랜드에만** 적용한다. 실패했거나 수집 범위 한계에
    걸린 브랜드는 collect_brands가 complete_brands에서 빼주므로, 못 본 매물을
    사라진 것으로 오해하지 않는다.
    """
    collected, complete_jobs, health_by_job = await collect_jobs(
        source_name=source_name,
        jobs=SEARCH_PLAN,
        crawl_job=crawl_job,
    )

    saved = await upsert_items(collected.items)

    if complete_jobs:
        # 존재 증명(seen)은 라운드 전체 수집분을 쓴다 — 어느 잡에서 봤든 그 매물은
        # 살아 있다. 잡 완료 여부는 "못 봤음"을 믿어도 되는지에만 관여하므로,
        # 완료된 잡의 (브랜드, 카테고리) 범위에서만 미발견을 매긴다. seen을 잡별로
        # 좁히면 교차 유입(시계 검색에 걸린 가방)이 매 라운드 미발견으로 오판된다.
        seen_urls = {item.url for item in collected.items}

        for category in {job.category for job in complete_jobs}:
            scope = CrawlScope(
                source=source_name,
                brands=frozenset(
                    job.brand for job in complete_jobs if job.category == category
                ),
                category=category,
            )
            await sweep_missing(scope, seen_urls)
    else:
        logger.warning(
            "%s 완전히 훑은 검색 잡이 없어 미발견 정리를 건너뜁니다.", source_name
        )

    logger.info("%s 자동 크롤링 완료: 총 %s건", source_name, saved)

    return saved, {
        source_name: {
            label: health.to_dict() for label, health in health_by_job.items()
        }
    }


async def crawl_daangn_once() -> tuple[int, dict[str, dict]]:
    """당근마켓을 브랜드별로 한 바퀴 수집한다."""
    logger.info("당근마켓 자동 크롤링 시작")

    async def crawl_job(job: SearchJob):
        crawler = DaangnCrawler(
            DaangnCrawlerConfig(
                brand=job.brand,
                keyword_suffix=job.suffix,
                headless=True,
                scroll_count=6,
            )
        )
        return await crawler.crawl()

    return await _collect_and_store(source_name=DAANGN, crawl_job=crawl_job)


async def crawl_joongna_once() -> tuple[int, dict[str, dict]]:
    """중고나라를 브랜드별로 한 바퀴 수집한다."""
    logger.info("중고나라 자동 크롤링 시작")

    async def crawl_job(job: SearchJob):
        crawler = JoongnaCrawler(
            JoongnaCrawlerConfig(
                brand=job.brand,
                keyword_suffix=job.suffix,
                headless=True,
                max_pages=JOONGNA_PAGES_PER_BRAND,
            )
        )
        return await crawler.crawl()

    return await _collect_and_store(source_name=JOONGNA, crawl_job=crawl_job)


# 한 라운드에서 순서대로 실행할 작업. 사이트를 추가하려면 함수 하나를 만들어
# 여기에 넣으면 되고, 실행 규칙(주기·재시도·기록)은 손댈 필요가 없다.
async def crawl_bunjang_once() -> tuple[int, dict[str, dict]]:
    async def crawl_job(job: SearchJob):
        crawler = BunjangCrawler(
            BunjangCrawlerConfig(
                brand=job.brand,
                keyword_suffix=job.suffix,
                max_pages=BUNJANG_PAGES_PER_JOB,
            )
        )
        return await crawler.crawl()

    return await _collect_and_store(source_name=BUNJANG, crawl_job=crawl_job)


CRAWL_JOBS: tuple[CrawlJob, ...] = (
    crawl_daangn_once,
    crawl_joongna_once,
    crawl_bunjang_once,
)