# app/tests/test_listing_status.py

"""
판매 상태 표기 판정 테스트.

이 판정이 틀리면 두 가지가 망가진다.

1. **생명주기** — is_sold가 false로 잘못 나오면 팔린 매물이 목록에 남는다.
   미발견 3회를 기다려야 내려가므로 최소 1시간 30분이 밀린다.
2. **제목** — 배지 줄을 제목으로 잡으면 "판매완료"라는 제목의 매물이 DB에 쌓인다.
   실제로 중고나라 파서에 이 결함이 있었다.

두 사이트가 같은 규칙을 쓰는지도 함께 확인한다. 각자 구현하면 한쪽만 고치게 되고,
같은 상황의 매물이 사이트에 따라 다르게 취급된다.
"""

import pytest

from app.crawler.daangn.parser import parse_card_text as parse_daangn
from app.crawler.joongna.parser import parse_card_text as parse_joongna
from app.domain import listing_status

DAANGN_URL = "https://www.daangn.com/kr/buy-sell/abc-123/"
JOONGNA_URL = "https://web.joongna.com/product/1"


# ---------------------------------------------------------------------------
# 판정 규칙
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["판매완료", "거래완료", "판매 완료", "거래 완료", "판매완료 샤넬 클래식 플랩"],
)
def test_detects_sold(text):
    assert listing_status.is_sold(text) is True


@pytest.mark.parametrize("text", [None, "", "샤넬 클래식 플랩", "판매중", "예약중"])
def test_does_not_overdetect(text):
    """
    '판매중'을 판매완료로 읽으면 살아있는 매물이 전부 사라진다. 부분 문자열로 찾기
    때문에 이 경계를 명시적으로 확인한다.
    """
    assert listing_status.is_sold(text) is False


def test_reserved_is_not_sold():
    """
    예약은 취소될 수 있어서 판매완료와 구분한다. 지금은 is_sold로 취급하지 않고,
    예약된 매물이 목록에 남았다가 취소되면 그대로 유지되게 둔다.
    """
    assert listing_status.is_reserved("예약중") is True
    assert listing_status.is_sold("예약중") is False


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("판매완료샤넬 클래식 플랩", "샤넬 클래식 플랩"),
        ("판매완료 구찌 마몬트", "구찌 마몬트"),
        ("예약중 에르메스 버킨", "에르메스 버킨"),
        ("샤넬 클래식 플랩", "샤넬 클래식 플랩"),
        ("판매완료", ""),
    ],
)
def test_strips_leading_markers(line, expected):
    """배지와 제목이 한 줄로 합쳐져 오는 경우를 처리한다."""
    assert listing_status.strip_status_markers(line) == expected


@pytest.mark.parametrize("line", ["판매완료", "예약중", "인증셀러", "무료배송", "·", "  "])
def test_badge_lines_are_not_titles(line):
    assert listing_status.is_title_candidate(line) is False


def test_real_titles_are_accepted():
    assert listing_status.is_title_candidate("샤넬 클래식 플랩") is True


# ---------------------------------------------------------------------------
# 중고나라 파서 — 이번에 판정이 추가된 쪽
# ---------------------------------------------------------------------------


def test_joongna_detects_sold():
    parsed = parse_joongna(
        "판매완료\n샤넬 클래식 플랩\n4,500,000원\n3일 전", url=JOONGNA_URL
    )

    assert parsed["is_sold"] is True


def test_joongna_badge_does_not_become_title():
    """
    이게 이번 수정의 핵심이다. 예전에는 배지 줄이 첫 번째 의미 있는 줄이라
    제목이 "판매완료"가 됐다.
    """
    parsed = parse_joongna(
        "판매완료\n샤넬 클래식 플랩\n4,500,000원", url=JOONGNA_URL
    )

    assert parsed["title"] == "샤넬 클래식 플랩"


def test_joongna_inline_badge_is_stripped():
    parsed = parse_joongna("인증셀러\n판매완료구찌 마몬트\n300,000원", url=JOONGNA_URL)

    assert parsed["title"] == "구찌 마몬트"
    assert parsed["is_sold"] is True


def test_joongna_normal_item_is_not_sold():
    parsed = parse_joongna("샤넬 클래식 플랩\n4,500,000원\n3일 전", url=JOONGNA_URL)

    assert parsed["is_sold"] is False
    assert parsed["title"] == "샤넬 클래식 플랩"


def test_joongna_price_still_parsed_after_badge():
    """배지 처리를 넣으면서 가격 인식이 깨지지 않았는지 확인한다."""
    parsed = parse_joongna("판매완료\n구찌 마몬트\n1,200,000원", url=JOONGNA_URL)

    assert parsed["price"] == "1,200,000원"


# ---------------------------------------------------------------------------
# 두 사이트가 같은 규칙을 쓰는가
# ---------------------------------------------------------------------------


def test_daangn_still_detects_sold():
    parsed = parse_daangn(
        "판매완료\n샤넬 클래식 플랩\n역삼동\n4,500,000원\n3일 전", url=DAANGN_URL
    )

    assert parsed["is_sold"] is True
    assert parsed["title"] == "샤넬 클래식 플랩"


@pytest.mark.parametrize("marker", sorted(listing_status.SOLD_MARKERS))
def test_both_sites_agree_on_markers(marker):
    """
    같은 표기를 한쪽만 인식하면 사이트에 따라 매물 취급이 달라진다.
    공유 모듈로 뺀 이유가 이것이다.
    """
    daangn = parse_daangn(
        f"{marker}\n샤넬 클래식 플랩\n역삼동\n4,500,000원", url=DAANGN_URL
    )
    joongna = parse_joongna(f"{marker}\n샤넬 클래식 플랩\n4,500,000원", url=JOONGNA_URL)

    assert daangn["is_sold"] is True, f"당근이 '{marker}'를 인식하지 못한다"
    assert joongna["is_sold"] is True, f"중고나라가 '{marker}'를 인식하지 못한다"
    assert daangn["title"] == joongna["title"] == "샤넬 클래식 플랩"