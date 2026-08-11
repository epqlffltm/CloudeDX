# app/crawler/joongna/crawler.py

"""
중고나라(joongna) 검색 결과 크롤러. Playwright 기반, 비동기.
공통 엔진(app.crawler.base)을 사용 — 당근마켓 크롤러와 동일한 방식으로 통일했다.

DB 저장은 여기서 하지 않는다.
"""

import asyncio
from urllib.parse import quote

from playwright.async_api import async_playwright

from app.crawler.base import EngineConfig, collect_cards, create_browser_context, scroll_page
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.parser import parse_card_text, parse_price_value
from app.crawler.models import CrawledItem

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
            is_sold=False,  # 원본 스크립트에 판매완료 판별 로직이 없어 기본값으로 둔다
        )

    async def _collect_page(self, page, page_num: int) -> list[dict]:
        target_url = self._build_url(page_num)
        print(f"[joongna] [{page_num} 페이지] 접속 중: {target_url}")

        await page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=self.config.timeout_ms,
        )
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

    async def crawl(self) -> list[CrawledItem]:
        engine_config = EngineConfig(
            headless=self.config.headless,
            timeout_ms=self.config.timeout_ms,
        )
        all_parsed: dict[str, dict] = {}

        async with async_playwright() as p:
            browser, context = await create_browser_context(p, engine_config)
            page = await context.new_page()
            page.set_default_timeout(self.config.timeout_ms)

            try:
                for page_num in range(1, self.config.max_pages + 1):
                    try:
                        page_items = await self._collect_page(page, page_num)
                    except Exception as exc:
                        print(
                            f"[joongna] {page_num} 페이지 진행 중 오류, "
                            f"다음 페이지로 건너뜀: {exc}"
                        )
                        continue

                    if not page_items:
                        print(
                            f"[joongna] {page_num} 페이지에서 상품을 찾지 못해 수집을 마칩니다."
                        )
                        break

                    for parsed in page_items:
                        all_parsed[parsed["url"]] = parsed

                    print(
                        f"[joongna]    └ {len(page_items)}개 수집 "
                        f"(누적: {len(all_parsed)}개)"
                    )
                    await asyncio.sleep(self.config.between_page_pause_seconds)
            finally:
                await browser.close()

        return [self._to_item(parsed) for parsed in all_parsed.values()]
