# app/tests/test_joongna_parser.py

"""
app.crawler.joongna.parser의 순수 함수 테스트.
Playwright/브라우저 없이도 카드 텍스트 파싱 규칙만 검증한다.
"""

from app.crawler.joongna.parser import parse_card_text, parse_price_value


def test_parse_card_text_extracts_title_and_price():
    raw_text = "인증셀러\n구찌 숄더백 정품\n350,000원\n무료배송"

    result = parse_card_text(raw_text, url="https://web.joongna.com/product/1")

    assert result is not None
    assert result["title"] == "구찌 숄더백 정품"
    assert result["price"] == "350,000원"
    assert result["url"] == "https://web.joongna.com/product/1"


def test_parse_card_text_returns_none_for_sell_button_card():
    raw_text = "판매하기"

    result = parse_card_text(raw_text, url="https://web.joongna.com/product/2")

    assert result is None


def test_parse_card_text_handles_missing_price():
    raw_text = "구찌 반지갑"

    result = parse_card_text(raw_text, url="https://web.joongna.com/product/3")

    assert result is not None
    assert result["price"] is None


def test_parse_price_value_extracts_digits():
    assert parse_price_value("350,000원") == 350000
    assert parse_price_value(None) is None
    assert parse_price_value("가격 정보 없음") is None
