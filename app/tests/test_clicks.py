# app/tests/test_clicks.py

"""
클릭 집계와 인기 레일.

지키려는 것 세 가지.

1. **한 세션·한 매물·30분에 한 번.** 연타·새로고침이 집계를 부풀리지 않는다.
   판정은 DB 유니크 제약이므로 실제 Postgres에서 확인한다.
2. **직접등록이 앞, 모자라면 크롤링이 채운다.** 인기 레일의 존재 이유다.
3. **세션은 서버가 정한다.** 쿠키가 없으면 굽고, 본문으로는 못 고른다.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import clicks, repository
from app.db.models import ItemClickEvent, ItemRecord
from app.domain.clicks import BUCKET_WIDTH, bucket_start, session_hash
from app.domain.models import CrawledItem
from app.domain.sources import UPLOAD
from app.routers.events import CLIENT_ID_COOKIE


def make_item(url: str, *, source: str = "중고나라", title: str = "샤넬 클래식 플랩"):
    return CrawledItem(
        source=source,
        brand="샤넬",
        title=title,
        price="4,000,000원",
        price_value=4_000_000,
        region="서초구",
        time_text="3시간 전",
        image_url=None,
        url=url,
        is_sold=False,
        seller_type=None,
    )


async def _click_count(session, item_id: int) -> int:
    session.expire_all()
    row = await session.get(ItemRecord, item_id)
    return row.click_count


# ── 순수 규칙 ─────────────────────────────────────────────────────────


def test_bucket_floors_to_30_minutes():
    at = datetime(2026, 8, 31, 10, 47, 13, tzinfo=UTC)
    assert bucket_start(at) == datetime(2026, 8, 31, 10, 30, tzinfo=UTC)
    assert bucket_start(at + BUCKET_WIDTH) == datetime(2026, 8, 31, 11, 0, tzinfo=UTC)


def test_bucket_rejects_naive_datetime():
    import pytest

    with pytest.raises(ValueError):
        bucket_start(datetime(2026, 8, 31, 10, 47))


def test_session_hash_is_stable_and_secret_bound():
    a = session_hash("abc", "k1")
    assert a == session_hash("abc", "k1")
    assert a != session_hash("abc", "k2")
    assert a != session_hash("abd", "k1")
    assert len(a) == 64


# ── 저장 규칙 ─────────────────────────────────────────────────────────


async def test_same_bucket_counts_once(session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    bucket = bucket_start(datetime.now(UTC))

    assert await clicks.record_click(session, 1, "s1", bucket) is True
    assert await clicks.record_click(session, 1, "s1", bucket) is False
    await session.commit()

    assert await _click_count(session, 1) == 1


async def test_next_bucket_counts_again(session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    bucket = bucket_start(datetime.now(UTC))

    await clicks.record_click(session, 1, "s1", bucket)
    await clicks.record_click(session, 1, "s1", bucket + BUCKET_WIDTH)
    await session.commit()

    assert await _click_count(session, 1) == 2


async def test_different_sessions_count_separately(session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    bucket = bucket_start(datetime.now(UTC))

    await clicks.record_click(session, 1, "s1", bucket)
    await clicks.record_click(session, 1, "s2", bucket)
    await session.commit()

    assert await _click_count(session, 1) == 2
    events = (await session.execute(select(ItemClickEvent))).scalars().all()
    assert len(events) == 2


# ── API ───────────────────────────────────────────────────────────────


async def test_click_endpoint_sets_cookie_and_dedupes(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    first = await client.post("/api/events/click", json={"item_id": 1})
    assert first.status_code == 202
    assert first.json() == {"status": "counted"}
    assert CLIENT_ID_COOKIE in first.cookies

    # httpx 클라이언트가 쿠키를 들고 다시 보낸다 → 같은 세션, 같은 버킷.
    second = await client.post("/api/events/click", json={"item_id": 1})
    assert second.status_code == 202
    assert second.json() == {"status": "duplicate"}

    assert await _click_count(session, 1) == 1


async def test_click_endpoint_new_cookie_is_new_session(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    await client.post("/api/events/click", json={"item_id": 1})
    client.cookies.clear()
    res = await client.post("/api/events/click", json={"item_id": 1})

    assert res.json() == {"status": "counted"}
    assert await _click_count(session, 1) == 2


async def test_click_endpoint_ignores_forged_cookie_shape(client, session):
    """모양이 이상한 쿠키는 버리고 새로 굽는다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    client.cookies.set(CLIENT_ID_COOKIE, "not-a-hex-token")
    res = await client.post("/api/events/click", json={"item_id": 1})

    assert res.status_code == 202
    assert res.cookies.get(CLIENT_ID_COOKIE) not in (None, "not-a-hex-token")


async def test_click_endpoint_unknown_item_is_404(client):
    res = await client.post("/api/events/click", json={"item_id": 999})
    assert res.status_code == 404


async def test_click_endpoint_rejects_bad_body(client):
    assert (await client.post("/api/events/click", json={"item_id": 0})).status_code == 422
    assert (await client.post("/api/events/click", json={})).status_code == 422


# ── 인기 레일 ─────────────────────────────────────────────────────────


async def test_popular_puts_direct_first_then_fills_with_crawled(client, session):
    """직접등록은 클릭 0이어도 앞. 나머지는 클릭 많은 순, 같으면 최신순."""
    await repository.upsert_items(
        [
            make_item("https://ex.com/c1", title="샤넬 클래식 플랩 크롤1"),
            make_item("https://ex.com/c2", title="샤넬 클래식 플랩 크롤2"),
            make_item("https://ex.com/c3", title="샤넬 클래식 플랩 크롤3"),
            make_item("https://ex.com/d1", source=UPLOAD, title="샤넬 클래식 플랩 직접1"),
        ]
    )
    bucket = bucket_start(datetime.now(UTC))

    # 제목에 브랜드·품목 키워드가 있어야 정제(is_usable)를 통과한다.
    # 크롤2에 클릭 2, 크롤1에 클릭 1, 직접1과 크롤3은 0.
    await clicks.record_click(session, 2, "a", bucket)
    await clicks.record_click(session, 2, "b", bucket)
    await clicks.record_click(session, 1, "a", bucket)
    await session.commit()

    body = (await client.get("/api/products/popular?limit=3")).json()
    titles = [it["title"] for it in body["items"]]

    assert titles == [
        "샤넬 클래식 플랩 직접1", "샤넬 클래식 플랩 크롤2", "샤넬 클래식 플랩 크롤1",
    ]
    assert body["count"] == 3
    assert body["has_next"] is False


async def test_popular_excludes_inactive(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    await session.execute(
        ItemRecord.__table__.update().where(ItemRecord.id == 1).values(is_active=False)
    )
    await session.commit()

    body = (await client.get("/api/products/popular")).json()
    assert body["items"] == []


async def test_popular_keeps_listing_contract(client, session):
    """인기 응답도 ListingOut 그대로 — click_count가 새어 나가지 않는다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    listing = (await client.get("/api/products/popular")).json()["items"][0]
    assert "click_count" not in listing
    assert set(listing) == {
        "id", "source", "title", "brand", "category", "price",
        "image_url", "item_url", "seller_id", "is_authenticated",
    }


async def test_popular_path_does_not_shadow_item_detail(client, session):
    """/products/popular를 앞에 둬도 /products/{id}는 그대로 동작한다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    assert (await client.get("/api/products/1")).status_code == 200
    assert (await client.get("/api/products/popular")).status_code == 200
