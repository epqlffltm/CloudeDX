# app/tests/test_timeparse.py

"""
app.domain.timeparse 테스트.

DB도 브라우저도 필요 없는 순수 함수라 빠르게 돈다. 이 변환이 틀리면 게시판의
등록 시각과 정렬이 통째로 어긋나므로 경계값을 촘촘히 확인한다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import CrawledItem
from app.domain.timeparse import find_relative_time_text, parse_relative_time

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("방금 전", NOW),
        ("30초 전", NOW - timedelta(seconds=30)),
        ("5분 전", NOW - timedelta(minutes=5)),
        ("3시간 전", NOW - timedelta(hours=3)),
        ("2일 전", NOW - timedelta(days=2)),
        ("1주 전", NOW - timedelta(weeks=1)),
        ("2개월 전", NOW - timedelta(days=60)),
        ("3달 전", NOW - timedelta(days=90)),
        ("1년 전", NOW - timedelta(days=365)),
    ],
)
def test_parses_relative_time(text, expected):
    assert parse_relative_time(text, NOW) == expected


def test_parses_bumped_post():
    """
    당근의 '끌올'은 판매자가 글을 상단으로 올린 시각이라 최초 등록일이 아니다.
    사이트가 원래 등록일을 노출하지 않으므로 목록 수집만으로는 구분할 수 없고,
    여기서는 접두어를 떼고 시각만 읽는다.
    """
    assert parse_relative_time("끌올 2일 전", NOW) == NOW - timedelta(days=2)


def test_finds_time_inside_other_text():
    """
    중고나라 카드는 시각 표기가 어느 줄에 붙어 나올지 카드마다 달라서 원문 전체를
    훑는다.
    """
    raw = "샤넬 클래식 플랩\n4,500,000원\n3일 전\n무료배송"

    assert find_relative_time_text(raw) == "3일 전"
    assert parse_relative_time(raw, NOW) == NOW - timedelta(days=3)


@pytest.mark.parametrize("text", [None, "", "가격문의", "무료배송", "인증셀러"])
def test_returns_none_for_unparseable(text):
    """해석할 수 없으면 None이다. 이 경우 화면은 first_seen_at으로 대체한다."""
    assert parse_relative_time(text, NOW) is None
    assert find_relative_time_text(text) is None


def test_crawled_item_exposes_posted_at():
    """
    posted_at을 필드가 아니라 프로퍼티로 둔 이유는 두 크롤러가 각자 계산하면
    로직이 갈라지기 때문이다.
    """
    item = CrawledItem(
        source="당근마켓",
        brand="샤넬",
        title="t",
        price=None,
        price_value=None,
        region=None,
        time_text="3시간 전",
        image_url=None,
        url="https://ex.com/1",
        is_sold=False,
    )

    assert item.posted_at is not None
    assert item.posted_at < datetime.now(UTC)


def test_crawled_item_posted_at_is_none_without_time_text():
    item = CrawledItem(
        source="중고나라",
        brand="구찌",
        title="t",
        price=None,
        price_value=None,
        region=None,
        time_text=None,
        image_url=None,
        url="https://ex.com/2",
        is_sold=False,
    )

    assert item.posted_at is None