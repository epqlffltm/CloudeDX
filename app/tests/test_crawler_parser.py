# app/tests/test_crawler_parser.py

"""
app.crawler.daangn.parser의 순수 함수 테스트.
브라우저 없이도 카드 텍스트 파싱 규칙만 검증한다.
"""

from app.crawler.daangn.parser import (
    is_item_detail_url,
    parse_card_text,
    parse_price_value,
)


def test_parse_card_text_extracts_title_price_region_time():
    raw_text = "샤넬 그랜드 쇼퍼백 블랙 은장\n역삼동\n4,500,000원\n3일 전"

    result = parse_card_text(
        raw_text,
        url="https://www.daangn.com/kr/buy-sell/abc-123/",
    )

    assert result is not None
    assert result["title"] == "샤넬 그랜드 쇼퍼백 블랙 은장"
    assert result["region"] == "역삼동"
    assert result["price"] == "4,500,000원"
    assert result["time_text"] == "3일 전"
    assert result["is_sold"] is False


def test_parse_card_text_detects_sold_items():
    raw_text = "판매완료 구찌 반지갑\n서초동\n350,000원\n방금 전"

    result = parse_card_text(
        raw_text,
        url="https://www.daangn.com/kr/buy-sell/def-456/",
    )

    assert result is not None
    assert result["is_sold"] is True


def test_parse_card_text_returns_none_without_title():
    result = parse_card_text("", url="https://www.daangn.com/kr/buy-sell/ghi-789/")
    assert result is None


def test_is_item_detail_url():
    assert is_item_detail_url("https://www.daangn.com/kr/buy-sell/abc-123/") is True
    assert is_item_detail_url("https://www.daangn.com/kr/buy-sell/") is False
    assert is_item_detail_url(None) is False


def test_parse_price_value_extracts_digits_and_handles_donation():
    assert parse_price_value("4,500,000원") == 4500000
    assert parse_price_value("나눔") == 0
    assert parse_price_value(None) is None
