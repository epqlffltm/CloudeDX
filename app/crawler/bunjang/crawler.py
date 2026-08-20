# app/crawler/bunjang/crawler.py

"""
번개장터 검색 API 크롤러. 세 수집처 중 유일하게 브라우저가 없다 —
공개 JSON API(find_v2)를 httpx로 호출하므로 Playwright 계층이 통째로 빠진다.
페이지 순회·완전성 판정은 당근·중나와 같은 공통 엔진(collect_pages)을 쓴다.

DB 저장은 여기서 하지 않는다.
"""

import logging

import httpx

from app.crawler.bunjang.config import BunjangCrawlerConfig
from app.crawler.bunjang.parser import parse_api_item
from app.crawler.source_runner import collect_pages
from app.domain.collection import Collection
from app.domain.models import CrawledItem
from app.domain.parse_health import ParseHealth

logger = logging.getLogger(__name__)

API_URL = "https://api.bunjang.co.kr/api/1/find_v2.json"

# 원본 스크립트에서 검증된 헤더 — 모바일 웹 출처를 흉내 낸다.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://m.bunjang.co.kr/",
}


class BunjangCrawler:
    def __init__(
        self,
        config: BunjangCrawlerConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.config = config or BunjangCrawlerConfig()
        # 테스트가 MockTransport를 단 클라이언트를 주입한다.
        # 실전에서는 crawl()이 스스로 만들고 닫는다.
        self._injected_client = client

    def _params(self, api_page: int) -> dict:
        return {
            "q": self.config.keyword,
            "order": "score",
            "page": api_page,
            "f_category_id": "",
            "f_brand_id": self.config.brand_id,
            # 원본 스크립트의 값. 판매중만 내려주는 필터로 추정된다 —
            # 실측 확인 항목이고, 그래서 is_sold는 항상 False로 둔다.
            # 판매완료로 사라진 매물은 미발견 정리(sweep)가 담당한다.
            "status": "0",
        }

    async def _collect_page(self, client: httpx.AsyncClient, page_num: int) -> list[dict]:
        # 공통 엔진은 1부터 세고, 번개장터 API는 0부터 센다.
        response = await client.get(API_URL, params=self._params(page_num - 1))
        response.raise_for_status()

        items = response.json().get("list", [])
        self._health.seen += len(items)

        parsed_items: list[dict] = []

        for item in items:
            self._health.attempted += 1
            parsed = parse_api_item(item)

            if parsed is None:
                continue

            self._health.parsed += 1
            parsed_items.append(parsed)

        logger.info(
            "[bunjang] [%s 페이지] %d개 수집", page_num, len(parsed_items)
        )

        return parsed_items

    def _to_item(self, parsed: dict) -> CrawledItem:
        return CrawledItem(
            source="번개장터",
            brand=self.config.brand,
            title=parsed["title"],
            price=parsed["price"],
            price_value=parsed["price_value"],
            region=None,  # API 검색 결과에 지역 정보가 없다
            # 응답에 등록 시각 필드가 있는지 실측 전이라 넣지 않는다 —
            # 모르는 값을 추정으로 채우지 않는다.
            time_text=None,
            image_url=parsed["image_url"],
            url=parsed["url"],
            is_sold=False,
            seller_type=None,
        )

    async def crawl(self) -> Collection[CrawledItem]:
        self._health = ParseHealth()

        client = self._injected_client or httpx.AsyncClient(
            headers=_HEADERS, timeout=self.config.timeout_seconds
        )

        try:
            async def collect_page(page_num: int) -> list[dict]:
                return await self._collect_page(client, page_num)

            collected = await collect_pages(
                source_name=f"번개장터 '{self.config.brand}'",
                max_pages=self.config.max_pages,
                collect_page=collect_page,
                between_page_pause_seconds=self.config.between_page_pause_seconds,
            )
        finally:
            if self._injected_client is None:
                await client.aclose()

        # 같은 매물이 여러 페이지에 다시 노출될 수 있으므로 URL 기준으로 접는다.
        all_parsed = {parsed["url"]: parsed for parsed in collected.items}

        collection = Collection(
            items=[self._to_item(parsed) for parsed in all_parsed.values()],
            complete=collected.complete,
            health=self._health,
        )
        collection.apply_parse_health()

        return collection
