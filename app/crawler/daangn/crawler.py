# app/crawler/daangn/crawler.py

"""
당근마켓 검색 결과 크롤러. Playwright 기반, 비동기.
공통 엔진(app.crawler.base)을 사용해서 브라우저 실행/스크롤/카드 수집 흐름은
중고나라 크롤러와 공유하고, URL 생성 · 셀렉터 · 텍스트 파싱만 당근마켓에 맞게 구현한다.

DB 저장은 여기서 하지 않는다.
"""

from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.crawler.base import EngineConfig, collect_cards, create_browser_context, scroll_page
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.parser import (
    is_item_detail_url,
    parse_card_text,
    parse_price_value,
)
from app.domain.models import CrawledItem

ITEM_LINK_SELECTOR = "a[href*='/kr/buy-sell/']"


class DaangnCrawler:
    def __init__(self, config: DaangnCrawlerConfig | None = None):
        self.config = config or DaangnCrawlerConfig()

    def _build_search_url(self) -> str:
        query = self.config.query.strip()

        if not query:
            raise ValueError("검색어(query)는 비어 있을 수 없습니다.")

        params = {"search": query}

        # 당근 검색 URL의 in 파라미터는 사람이 읽는 '강남구'가 아니라
        # 예: '성수동2가-6141' 같은 지역 코드/slug 형태다.
        if self.config.region_code:
            params["in"] = self.config.region_code.strip()

        return f"{self.config.base_url}?{urlencode(params)}"

    def _resolve_url(self, href: str) -> str | None:
        url = href if href.startswith("http") else f"https://www.daangn.com{href}"
        return url if is_item_detail_url(url) else None

    def _parse_card(self, raw_text: str, url: str, image_url: str | None) -> dict | None:
        return parse_card_text(raw_text, url=url, image_url=image_url)

    def _to_item(self, parsed: dict) -> CrawledItem:
        return CrawledItem(
            source="당근마켓",
            brand=self.config.brand,
            title=parsed["title"],
            price=parsed["price"],
            price_value=parse_price_value(parsed["price"]),
            region=parsed["region"],
            time_text=parsed["time_text"],
            image_url=parsed["image_url"],
            url=parsed["url"],
            is_sold=parsed["is_sold"],
        )

    async def crawl(self) -> list[CrawledItem]:
        engine_config = EngineConfig(
            headless=self.config.headless,
            timeout_ms=self.config.timeout_ms,
        )

        async with async_playwright() as p:
            browser, context = await create_browser_context(p, engine_config)
            page = await context.new_page()
            page.set_default_timeout(self.config.timeout_ms)

            try:
                url = self._build_search_url()
                print(f"[daangn] 접속 중: {url}")

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.config.timeout_ms,
                )

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
            finally:
                await browser.close()

        return [self._to_item(parsed) for parsed in cards.values()]

