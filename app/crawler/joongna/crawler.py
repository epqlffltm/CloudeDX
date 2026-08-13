# app/crawler/joongna/crawler.py

"""
중고나라(joongna) 검색 결과 크롤러. Playwright 기반, 비동기.
공통 엔진(app.crawler.base)을 사용 — 당근마켓 크롤러와 동일한 방식으로 통일했다.

DB 저장은 여기서 하지 않는다.

페이지 하나가 실패하면 다음 페이지를 계속 시도한다. 단, 시도한 모든 페이지가 예외로
실패했다면 빈 리스트를 정상 결과처럼 반환하지 않고 예외를 올린다. 그래야 상위의
브랜드/사이트 실패 정책이 실제 장애와 정상적인 "검색 결과 0건"을 구분할 수 있다.
"""

import asyncio
import logging
from urllib.parse import quote

from playwright.async_api import async_playwright

from app.crawler.base import EngineConfig, collect_cards, create_browser_context, scroll_page
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.parser import parse_card_text, parse_price_value
from app.crawler.source_runner import collect_pages
from app.domain.collection import Collection
from app.domain.models import CrawledItem

logger = logging.getLogger(__name__)

ITEM_LINK_SELECTOR = "a[href*='/product/']"


class JoongnaCrawler:
    def __init__(self, config: JoongnaCrawlerConfig | None = None):
        self.config = config or JoongnaCrawlerConfig()

    def _build_url(self, page_num: int) -> str:
        # keyword가 "구찌 가방"처럼 공백을 포함할 수 있어서 경로 세그먼트로 넣기 전에 인코딩한다.
        encoded_keyword = quote(self.config.keyword)
        return (
            f"https://web.joongna.com/search/{encoded_keyword}"
            f"?page={page_num}&category={self.config.category}"
        )

    def _resolve_url(self, href: str) -> str | None:
        return f"https://web.joongna.com{href}" if href.startswith("/") else href

    def _parse_card(self, raw_text: str, url: str, image_url: str | None) -> dict | None:
        return parse_card_text(raw_text, url=url, image_url=image_url)

    def _to_item(self, parsed: dict) -> CrawledItem:
        return CrawledItem(
            source="중고나라",
            brand=self.config.brand,
            title=parsed["title"],
            price=parsed["price"],
            price_value=parse_price_value(parsed["price"]),
            region=None,  # 중고나라 카드에는 지역 정보가 없다
            # 카드 원문에 '3일 전' 같은 표기가 있으면 파서가 뽑아준다. 없으면 None이고,
            # CrawledItem.posted_at도 따라서 None이 된다.
            time_text=parsed.get("time_text"),
            image_url=parsed["image_url"],
            url=parsed["url"],
            # 파서가 카드 원문에서 판매완료 배지를 찾아 넣어준다.
            # 값이 없는 옛 데이터를 대비해 기본값을 False로 둔다.
            is_sold=parsed.get("is_sold", False),
            seller_type=parsed.get("seller_type"),
        )

    async def _collect_page(self, page, page_num: int) -> list[dict]:
        target_url = self._build_url(page_num)
        logger.info("[joongna] [%s 페이지] 접속 중: %s", page_num, target_url)

        await page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=self.config.timeout_ms,
        )

        # 페이지 로딩 직후 동적 카드가 붙을 시간을 준다.
        # 실제 페이지 간 간격은 source_runner.collect_pages()가 별도로 적용한다.
        await asyncio.sleep(2)

        await scroll_page(
            page,
            count=self.config.scroll_count,
            pause_seconds=self.config.scroll_pause_seconds,
        )

        cards = await collect_cards(
            page,
            link_selector=ITEM_LINK_SELECTOR,
            resolve_url=self._resolve_url,
            parse_card=self._parse_card,
        )
        return list(cards.values())

    async def crawl(self) -> Collection[CrawledItem]:
        engine_config = EngineConfig(
            headless=self.config.headless,
            timeout_ms=self.config.timeout_ms,
        )

        async with async_playwright() as p:
            browser, context = await create_browser_context(p, engine_config)
            page = await context.new_page()
            page.set_default_timeout(self.config.timeout_ms)

            try:
                async def collect_page(page_num: int) -> list[dict]:
                    return await self._collect_page(page, page_num)

                collected = await collect_pages(
                    source_name=f"중고나라 '{self.config.brand}'",
                    max_pages=self.config.max_pages,
                    collect_page=collect_page,
                    between_page_pause_seconds=self.config.between_page_pause_seconds,
                )
            finally:
                await browser.close()

        # 같은 URL이 여러 페이지에 다시 노출될 수 있으므로 마지막 값으로 중복 제거한다.
        all_parsed = {parsed["url"]: parsed for parsed in collected.items}

        return Collection(
            items=[self._to_item(parsed) for parsed in all_parsed.values()],
            complete=collected.complete,
        )