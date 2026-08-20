# app/tests/test_bunjang.py

"""
번개장터 크롤러 검증. 실제 API는 부르지 않는다 — httpx.MockTransport로
응답 시퀀스를 심어 파싱·페이지 순회·완전성 판정·성적 계측까지 전체 흐름을 돈다.
파서 단위 케이스와 크롤러 통합 케이스로 나뉜다.
"""

import httpx
import pytest

from app.crawler.bunjang.config import BunjangCrawlerConfig
from app.crawler.bunjang.crawler import BunjangCrawler
from app.crawler.bunjang.parser import parse_api_item

# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------


def test_parses_normal_item():
    parsed = parse_api_item(
        {"pid": 12345, "name": " 구찌 마몬트 숄더백 ", "price": "1500000",
         "product_image": "https://img.bunjang.co.kr/x.jpg"}
    )

    assert parsed["title"] == "구찌 마몬트 숄더백"
    assert parsed["price_value"] == 1_500_000
    assert parsed["price"] == "1,500,000원", "표시 문자열은 다른 소스와 같은 형식으로 합성"
    assert parsed["url"] == "https://m.bunjang.co.kr/products/12345"


def test_rejects_item_without_pid():
    """pid가 없으면 매물 URL을 만들 수 없다 — 버린다."""
    assert parse_api_item({"name": "제목만 있는 항목", "price": 10000}) is None


@pytest.mark.parametrize("price", [0, "0", None, "가격문의"])
def test_zero_or_invalid_price_becomes_unknown(price):
    """0원(나눔·미기재)을 그대로 저장하면 최저가 정렬 맨 앞이 오염된다."""
    parsed = parse_api_item({"pid": 1, "name": "나눔합니다", "price": price})

    assert parsed["price_value"] is None
    assert parsed["price"] is None


# ---------------------------------------------------------------------------
# 크롤러 (MockTransport)
# ---------------------------------------------------------------------------


def make_client(pages: dict[int, list[dict]]) -> httpx.AsyncClient:
    """API 페이지 번호(0부터) → 항목 목록을 응답하는 가짜 클라이언트."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        return httpx.Response(200, json={"list": pages.get(page, [])})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def api_item(pid: int, name: str, price: int = 100_000) -> dict:
    return {"pid": pid, "name": name, "price": price, "product_image": ""}


async def test_stops_at_empty_page_and_is_complete():
    """빈 페이지를 만나 멈추면 끝까지 본 것 — complete=True가 sweep의 근거다."""
    crawler = BunjangCrawler(
        BunjangCrawlerConfig(brand="구찌", max_pages=5, between_page_pause_seconds=0),
        client=make_client({0: [api_item(1, "구찌 A")], 1: [api_item(2, "구찌 B")], 2: []}),
    )

    collection = await crawler.crawl()

    assert len(collection.items) == 2
    assert collection.complete is True
    assert collection.items[0].source == "번개장터"
    assert collection.items[0].is_sold is False


async def test_page_budget_exhausted_is_incomplete():
    """max_pages를 다 썼는데도 매물이 계속 나오면 불완전 — 4페이지로 밀린
    매물을 '사라졌다'고 오판하지 않기 위한 계약이다."""
    crawler = BunjangCrawler(
        BunjangCrawlerConfig(brand="구찌", max_pages=2, between_page_pause_seconds=0),
        client=make_client({0: [api_item(1, "A")], 1: [api_item(2, "B")], 2: [api_item(3, "C")]}),
    )

    collection = await crawler.crawl()

    assert len(collection.items) == 2
    assert collection.complete is False


async def test_broken_item_is_counted_as_parse_failure():
    crawler = BunjangCrawler(
        BunjangCrawlerConfig(brand="구찌", max_pages=1, between_page_pause_seconds=0),
        client=make_client({0: [api_item(1, "정상"), {"name": "pid 없음"}]}),
    )

    collection = await crawler.crawl()

    assert len(collection.items) == 1
    assert collection.health.attempted == 2
    assert collection.health.failed == 1


async def test_duplicate_urls_are_folded():
    """같은 매물이 두 페이지에 걸쳐 노출되면 한 건으로 접는다."""
    crawler = BunjangCrawler(
        BunjangCrawlerConfig(brand="구찌", max_pages=3, between_page_pause_seconds=0),
        client=make_client({0: [api_item(7, "중복")], 1: [api_item(7, "중복")], 2: []}),
    )

    collection = await crawler.crawl()

    assert len(collection.items) == 1
