# app/tests/test_joongna_parser.py

"""
app.crawler.joongna.parser의 순수 함수 테스트.
Playwright/브라우저 없이도 카드 텍스트 파싱 규칙만 검증한다.
"""

import pytest

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


# ---------------------------------------------------------------------------
# 가격 파싱 — 실제 카드 원문을 진단 도구로 확인한 뒤 추가한 케이스들
# ---------------------------------------------------------------------------


def test_price_unit_on_separate_line_is_joined():
    """
    중고나라는 금액과 단위를 별도 줄로 렌더링한다.

        250,000
        원

    금액만 저장하면 화면에 단위 없이 "250,000"으로 나온다. 실제 DB에 그렇게
    쌓여 있었다.
    """
    parsed = parse_card_text(
        "샤넬 골든볼 램스킨 뉴미니 가방\n250,000\n원\n1\n8분 전", url="https://x/1"
    )

    assert parsed["price"] == "250,000원"
    assert parse_price_value(parsed["price"]) == 250_000


@pytest.mark.parametrize("count", ["1", "51", "100", "999"])
def test_view_count_is_not_read_as_price(count):
    """
    카드에는 찜 개수·조회수가 숫자만 있는 줄로 섞여 들어온다. 예전 규칙("숫자만
    3자리 이상")에서는 찜 100개가 100원짜리 매물이 되어 최저가를 오염시켰다.
    """
    parsed = parse_card_text(f"구찌 마몬트\n{count}\n3시간 전", url="https://x/1")

    assert parsed["price"] is None


def test_unit_only_line_is_not_a_price():
    """
    금액이 최소값에 걸러진 뒤 다음 줄의 "원"을 가격으로 읽으면 price="원"이 저장된다.
    """
    parsed = parse_card_text("빈티지 파우치\n8,000\n원\n1시간 전", url="https://x/1")

    assert parsed["price"] is None


def test_price_with_unit_in_same_line():
    parsed = parse_card_text("샤넬 백\n1,200,000원\n2시간 전", url="https://x/1")

    assert parsed["price"] == "1,200,000원"


def test_extra_numeric_lines_after_price_are_ignored():
    """찜/조회 숫자가 가격 뒤에 여러 줄 오는 카드."""
    parsed = parse_card_text(
        "디올 오블리크 클러치백\n830,000\n원\n2\n1\n3시간 전", url="https://x/1"
    )

    assert parsed["price"] == "830,000원"
    assert parsed["title"] == "디올 오블리크 클러치백"