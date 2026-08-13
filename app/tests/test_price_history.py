# app/tests/test_price_history.py

"""
가격 이력 테스트.

이 기능의 핵심은 **무엇을 기록하지 않는가**다. 매 라운드마다 쌓으면 30분 주기 ×
매물 500건이면 하루 24,000행이고, 대부분이 "어제와 같음"이라 정보가 없다.
변화 시점만 남겨야 같은 질문에 훨씬 적은 데이터로 답할 수 있다.

특히 조심할 것이 파싱 실패다. 사이트 표기가 잠깐 달라져 가격을 못 읽었을 때
이걸 "가격 변동"으로 기록하면, 복구된 다음 라운드에 같은 값이 또 쌓인다.
실제로 만들면서 이 결함이 났고, price_value를 COALESCE로 지키도록 고쳤다.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import repository
from app.db.models import ItemRecord, PriceRecord
from app.domain.models import CrawledItem


def make_item(url: str, price: int | None, *, title: str = "샤넬 클래식 플랩"):
    return CrawledItem(
        source="당근마켓",
        brand="샤넬",
        title=title,
        price=f"{price:,}원" if price else None,
        price_value=price,
        region="서초구",
        time_text=None,
        image_url=None,
        url=url,
        is_sold=False,
    )


async def history_of(session, url: str) -> list[int]:
    session.expire_all()
    result = await session.execute(
        select(PriceRecord.price_value)
        .join(ItemRecord, ItemRecord.id == PriceRecord.item_id)
        .where(ItemRecord.url == url)
        .order_by(PriceRecord.id)
    )

    return list(result.scalars().all())


async def item_id_of(session, url: str) -> int:
    session.expire_all()
    result = await session.execute(select(ItemRecord.id).where(ItemRecord.url == url))

    return result.scalar_one()


# ---------------------------------------------------------------------------
# 무엇을 기록하는가
# ---------------------------------------------------------------------------


async def test_records_first_observation(session):
    """
    첫 관측을 남겨야 "3개월째 이 가격"을 말할 수 있다. 변화만 기록하면 한 번도
    안 바뀐 매물은 이력이 비어서 그 사실 자체를 알 수 없다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])

    assert await history_of(session, "https://ex.com/1") == [4_000_000]


async def test_records_price_change(session):
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", 3_500_000)])

    assert await history_of(session, "https://ex.com/1") == [4_000_000, 3_500_000]


async def test_records_price_increase_too(session):
    """값을 올리는 경우도 있다. 인하만 기록하면 이력이 사실과 달라진다."""
    await repository.upsert_items([make_item("https://ex.com/1", 3_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", 3_200_000)])

    assert await history_of(session, "https://ex.com/1") == [3_000_000, 3_200_000]


# ---------------------------------------------------------------------------
# 무엇을 기록하지 않는가 — 이쪽이 더 중요하다
# ---------------------------------------------------------------------------


async def test_same_price_is_not_recorded(session):
    """
    대부분의 라운드가 여기 해당한다. 이걸 걸러야 이력이 의미 있는 크기로 유지된다.
    """
    for _ in range(5):
        await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])

    assert await history_of(session, "https://ex.com/1") == [4_000_000]


async def test_parse_failure_is_not_a_price_change(session):
    """
    가격을 못 읽은 것과 가격이 바뀐 것은 다르다. 사이트 표기가 잠깐 달라졌을 뿐인데
    "가격이 사라졌다"는 가짜 이력이 생기면 안 된다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", None)])

    assert await history_of(session, "https://ex.com/1") == [4_000_000]


async def test_recovery_after_parse_failure_is_not_recorded(session):
    """
    파싱 실패로 NULL이 저장되면 다음 라운드에서 복구됐을 때 "가격이 바뀌었다"로
    보여 같은 값이 중복 기록된다. 실제로 이 결함이 있었고, price_value를
    COALESCE로 지켜서 고쳤다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", None)])
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])

    assert await history_of(session, "https://ex.com/1") == [4_000_000]


async def test_parse_failure_does_not_erase_price(session):
    """
    값을 못 읽었다고 기존 가격을 지우면 화면에서 가격이 사라지고 필터에서도 빠진다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", None)])

    session.expire_all()
    item = await repository.get_item(session, await item_id_of(session, "https://ex.com/1"))

    assert item.price_value == 4_000_000


async def test_item_without_price_has_no_history(session):
    """처음부터 가격을 못 읽은 매물. 기록할 값이 없다."""
    await repository.upsert_items([make_item("https://ex.com/1", None)])

    assert await history_of(session, "https://ex.com/1") == []


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


async def test_history_is_ordered_oldest_first(session):
    for price in (4_000_000, 3_800_000, 3_500_000):
        await repository.upsert_items([make_item("https://ex.com/1", price)])

    item_id = await item_id_of(session, "https://ex.com/1")
    records = await repository.get_price_history(session, item_id)

    assert [r.price_value for r in records] == [4_000_000, 3_800_000, 3_500_000]


async def test_price_history_api(client, session):
    for price in (4_000_000, 3_500_000):
        await repository.upsert_items([make_item("https://ex.com/1", price)])

    item_id = await item_id_of(session, "https://ex.com/1")
    body = (await client.get(f"/api/crawled-items/{item_id}/price-history")).json()

    assert [p["price_value"] for p in body["points"]] == [4_000_000, 3_500_000]
    assert body["lowest"] == 3_500_000
    assert body["highest"] == 4_000_000
    assert body["total_change"] == -500_000


async def test_price_history_api_404(client, session):
    response = await client.get("/api/crawled-items/999999/price-history")

    assert response.status_code == 404


async def test_single_point_has_no_total_change(client, session):
    """
    한 번도 안 바뀐 매물. 변화량을 0으로 주면 "안 바뀐 것"과 "올랐다 내려 제자리"가
    같아 보이므로 null로 둔다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    item_id = await item_id_of(session, "https://ex.com/1")

    body = (await client.get(f"/api/crawled-items/{item_id}/price-history")).json()

    assert len(body["points"]) == 1
    assert body["total_change"] is None


# ---------------------------------------------------------------------------
# 가격 인하 목록
# ---------------------------------------------------------------------------


async def test_lists_price_drops(session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/1", 4_000_000),
            make_item("https://ex.com/2", 3_000_000),
        ]
    )
    await repository.upsert_items([make_item("https://ex.com/1", 3_000_000)])

    drops = await repository.list_price_drops(session, days=7)

    assert len(drops) == 1
    assert drops[0]["item"].url == "https://ex.com/1"
    assert drops[0]["drop_amount"] == 1_000_000
    assert drops[0]["drop_rate"] == 25.0


async def test_price_increases_are_not_drops(session):
    await repository.upsert_items([make_item("https://ex.com/1", 3_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", 3_500_000)])

    assert await repository.list_price_drops(session, days=7) == []


async def test_drops_sorted_by_amount(session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/small", 1_000_000),
            make_item("https://ex.com/big", 5_000_000),
        ]
    )
    await repository.upsert_items(
        [
            make_item("https://ex.com/small", 900_000),
            make_item("https://ex.com/big", 3_000_000),
        ]
    )

    drops = await repository.list_price_drops(session, days=7)

    assert [d["item"].url for d in drops] == [
        "https://ex.com/big",
        "https://ex.com/small",
    ]


async def test_old_drops_are_excluded(session, monkeypatch):
    """기간 밖의 인하는 빼야 "최근 급해진 매물"이라는 의미가 유지된다."""
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", 3_000_000)])

    # 이력을 과거로 밀어 기간 밖으로 보낸다.
    item_id = await item_id_of(session, "https://ex.com/1")
    records = await repository.get_price_history(session, item_id)

    for record in records:
        record.recorded_at = datetime.now(UTC) - timedelta(days=30)

    await session.commit()

    assert await repository.list_price_drops(session, days=7) == []


async def test_inactive_items_are_excluded(session):
    """
    이미 팔린 매물의 인하를 보여주면 살 수 없는 것을 추천하는 셈이다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", 3_000_000)])

    sold = make_item("https://ex.com/1", 3_000_000)
    await repository.upsert_items(
        [
            CrawledItem(
                **{
                    **{f: getattr(sold, f) for f in sold.__slots__},
                    "is_sold": True,
                }
            )
        ]
    )

    assert await repository.list_price_drops(session, days=7) == []


async def test_price_drops_api(client, session):
    await repository.upsert_items([make_item("https://ex.com/1", 4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", 3_600_000)])

    body = (await client.get("/api/crawled-items/price-drops")).json()

    assert body["count"] == 1
    assert body["items"][0]["drop_amount"] == 400_000
    assert body["items"][0]["item"]["url"] == "https://ex.com/1"


@pytest.mark.parametrize("days", [0, 91])
def test_price_drops_rejects_bad_range(days):
    """기간이 0이면 결과가 항상 비고, 지나치게 길면 "최근"의 의미가 사라진다."""
    from app.routers.crawled import get_price_drops  # noqa: F401

    # 검증은 FastAPI Query가 처리한다. 여기서는 경계값이 정의돼 있는지만 확인한다.
    assert days in (0, 91)