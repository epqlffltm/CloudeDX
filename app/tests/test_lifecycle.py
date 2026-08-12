# app/tests/test_lifecycle.py

"""
매물 생명주기 테스트.

매물은 팔리거나 삭제되면 사이트에서 사라진다. 그런데 크롤링 결과에 없다는 것만으로는
"사라졌다"고 단정할 수 없다 — 수집 범위 밖으로 밀렸거나, 일시적 오류거나, 차단당해
빈 결과를 받았을 수 있다.

여기서 검증하는 규칙은 **오탐을 비탐보다 나쁘게 본다.** 사라진 매물이 하루 더 남아 있는
것보다, 멀쩡한 매물이 사라지는 쪽이 가격비교 서비스에 더 해롭기 때문이다. 그래서
확신이 없으면 건드리지 않는다.
"""

import pytest

from app.db import repository
from app.db.models import UnavailableReason
from app.domain.collection import CrawlScope
from app.domain.models import CrawledItem
from app.schemas.requests import CrawledItemFilterParams

ALL = CrawledItemFilterParams(include_inactive=True)


def make_item(url: str, *, brand: str = "샤넬", source: str = "당근마켓", is_sold: bool = False):
    return CrawledItem(
        source=source,
        brand=brand,
        title=f"{brand} 가방",
        price="4,000,000원",
        price_value=4_000_000,
        region="서초구",
        time_text="3시간 전",
        image_url=None,
        url=url,
        is_sold=is_sold,
    )


async def get_by_url(session, url: str):
    """
    upsert_items()와 sweep_missing()은 자체 세션에서 커밋하므로, 테스트 세션의
    ORM 캐시에는 갱신 전 객체가 남아 있다. 매번 만료시켜 DB에서 다시 읽는다.
    """
    session.expire_all()
    rows = await repository.list_items(session, ALL)
    return next(row for row in rows if row.url == url)


def scope(*brands: str, source: str = "당근마켓") -> CrawlScope:
    return CrawlScope(source=source, brands=frozenset(brands))


# ---------------------------------------------------------------------------
# 새 매물
# ---------------------------------------------------------------------------


async def test_new_item_is_active(session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    row = await get_by_url(session, "https://ex.com/1")

    assert row.is_active is True
    assert row.missing_count == 0
    assert row.unavailable_at is None
    assert row.unavailable_reason is None


async def test_sold_item_is_deactivated_immediately(session):
    """
    판매완료는 사이트가 알려준 사실이라 추정(미발견)과 달리 즉시 확정할 수 있다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", is_sold=True)])

    row = await get_by_url(session, "https://ex.com/1")

    assert row.is_active is False
    assert row.unavailable_reason == UnavailableReason.SOLD
    assert row.unavailable_at is not None


async def test_item_sold_after_being_active(session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    await repository.upsert_items([make_item("https://ex.com/1", is_sold=True)])

    row = await get_by_url(session, "https://ex.com/1")

    assert row.is_active is False
    assert row.is_sold is True
    assert row.unavailable_reason == UnavailableReason.SOLD


# ---------------------------------------------------------------------------
# 미발견 처리
# ---------------------------------------------------------------------------


async def test_one_miss_does_not_deactivate(session):
    """
    한 라운드 안 보였다고 내리면 오탐이 잦다. 사이트가 잠깐 느렸거나 검색 결과
    순서가 흔들렸을 수 있다.
    """
    await repository.upsert_items([make_item("https://ex.com/1")])

    result = await repository.sweep_missing(scope("샤넬"), seen_urls=set())

    row = await get_by_url(session, "https://ex.com/1")

    assert result == {"marked": 1, "deactivated": 0}
    assert row.is_active is True
    assert row.missing_count == 1


async def test_deactivates_after_threshold(session, monkeypatch):
    monkeypatch.setattr(repository, "MISSING_THRESHOLD", 3)

    await repository.upsert_items([make_item("https://ex.com/1")])

    for _ in range(2):
        await repository.sweep_missing(scope("샤넬"), seen_urls=set())

    row = await get_by_url(session, "https://ex.com/1")
    assert row.is_active is True, "임계값 전에는 유지돼야 한다"

    result = await repository.sweep_missing(scope("샤넬"), seen_urls=set())
    row = await get_by_url(session, "https://ex.com/1")

    assert result["deactivated"] == 1
    assert row.is_active is False
    assert row.missing_count == 3
    assert row.unavailable_reason == UnavailableReason.MISSING
    assert row.unavailable_at is not None


async def test_seen_item_is_untouched(session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    await repository.sweep_missing(scope("샤넬"), seen_urls={"https://ex.com/1"})

    row = await get_by_url(session, "https://ex.com/1")

    assert row.missing_count == 0
    assert row.is_active is True


async def test_reappearing_item_recovers(session, monkeypatch):
    """
    수집 범위 밖으로 잠깐 밀렸다가 돌아오는 경우가 실제로 있다. 되살아나야 한다.
    """
    monkeypatch.setattr(repository, "MISSING_THRESHOLD", 2)

    await repository.upsert_items([make_item("https://ex.com/1")])

    for _ in range(2):
        await repository.sweep_missing(scope("샤넬"), seen_urls=set())

    row = await get_by_url(session, "https://ex.com/1")
    assert row.is_active is False

    # 다시 발견
    await repository.upsert_items([make_item("https://ex.com/1")])
    row = await get_by_url(session, "https://ex.com/1")

    assert row.is_active is True
    assert row.missing_count == 0
    assert row.unavailable_at is None
    assert row.unavailable_reason is None


async def test_already_inactive_item_is_not_recounted(session):
    """
    판매완료로 확정된 것을 미발견으로 덮어쓰면 이유가 사실과 달라진다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", is_sold=True)])

    result = await repository.sweep_missing(scope("샤넬"), seen_urls=set())

    row = await get_by_url(session, "https://ex.com/1")

    assert result["marked"] == 0
    assert row.unavailable_reason == UnavailableReason.SOLD


# ---------------------------------------------------------------------------
# 범위 보호 — 이 프로젝트에서 가장 중요한 안전장치
# ---------------------------------------------------------------------------


async def test_other_brands_are_untouched(session):
    """
    브랜드 하나가 실패해도 나머지는 정상 판정할 수 있어야 하고, 그 반대도 마찬가지다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/chanel", brand="샤넬"),
            make_item("https://ex.com/gucci", brand="구찌"),
        ]
    )

    await repository.sweep_missing(scope("샤넬"), seen_urls=set())

    assert (await get_by_url(session, "https://ex.com/chanel")).missing_count == 1
    assert (await get_by_url(session, "https://ex.com/gucci")).missing_count == 0


async def test_other_sources_are_untouched(session):
    """당근을 훑었다고 중고나라 매물을 건드리면 안 된다."""
    await repository.upsert_items(
        [
            make_item("https://ex.com/d", source="당근마켓"),
            make_item("https://ex.com/j", source="중고나라"),
        ]
    )

    await repository.sweep_missing(scope("샤넬", source="당근마켓"), seen_urls=set())

    assert (await get_by_url(session, "https://ex.com/d")).missing_count == 1
    assert (await get_by_url(session, "https://ex.com/j")).missing_count == 0


async def test_empty_scope_is_noop(session):
    """
    완전히 훑은 브랜드가 하나도 없으면(전부 실패했거나 0건이면) 아무것도 하지 않는다.
    이게 없으면 사이트 차단 한 번에 전체 매물이 비활성 처리된다.
    """
    await repository.upsert_items([make_item("https://ex.com/1")])

    result = await repository.sweep_missing(scope(), seen_urls=set())

    assert result == {"marked": 0, "deactivated": 0}
    assert (await get_by_url(session, "https://ex.com/1")).missing_count == 0


# ---------------------------------------------------------------------------
# 조회 기본값
# ---------------------------------------------------------------------------


async def test_inactive_items_hidden_by_default(session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/active"),
            make_item("https://ex.com/sold", is_sold=True),
        ]
    )

    rows = await repository.list_items(session, CrawledItemFilterParams())

    assert {row.url for row in rows} == {"https://ex.com/active"}
    assert await repository.count_items(session, CrawledItemFilterParams()) == 1


async def test_include_inactive_returns_everything(session):
    """
    판매완료는 버릴 데이터가 아니다 — 실거래가에 가까워 시세 계산의 핵심 입력이다.
    화면에서 숨기는 것과 데이터에서 지우는 것은 다르다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/active"),
            make_item("https://ex.com/sold", is_sold=True),
        ]
    )

    rows = await repository.list_items(session, ALL)

    assert len(rows) == 2


@pytest.mark.parametrize("include_inactive", [True, False])
async def test_count_matches_list(session, include_inactive):
    """
    화면에 "N건"이라고 적어놓고 목록에는 다른 수가 나오면 사용자가 무엇을 믿을지
    모른다. count와 list가 같은 조건을 봐야 한다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/1"),
            make_item("https://ex.com/2", is_sold=True),
            make_item("https://ex.com/3"),
        ]
    )

    filters = CrawledItemFilterParams(include_inactive=include_inactive, limit=100)

    assert await repository.count_items(session, filters) == len(
        await repository.list_items(session, filters)
    )


async def test_api_hides_inactive_by_default(client, session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/active"),
            make_item("https://ex.com/sold", is_sold=True),
        ]
    )

    body = (await client.get("/api/crawled-items")).json()

    assert body["total"] == 1
    assert body["items"][0]["is_active"] is True

    with_inactive = (
        await client.get("/api/crawled-items", params={"include_inactive": "true"})
    ).json()

    assert with_inactive["total"] == 2


async def test_meta_counts_only_active(client, session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/1"),
            make_item("https://ex.com/2", is_sold=True),
        ]
    )

    body = (await client.get("/api/meta")).json()

    assert body["total_items"] == 1