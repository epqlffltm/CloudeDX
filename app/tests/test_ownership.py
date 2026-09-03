# app/tests/test_ownership.py

"""
매물 소유 검사.

기업고객은 자기 매물만 고칠 수 있어야 한다. 두 경로가 있다.
    CSV 업로드  — URL 이 같으면 upsert 가 덮어쓰므로, 크롤링 매물 URL 을 적으면
                  그 매물이 통째로 '직접등록'으로 바뀌던 구멍
    사진 등록   — 출처만 보고 판매자는 안 보던 구멍
"""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app import auth as auth_module
from app.db import repository
from app.db.models import ItemRecord
from app.domain.models import CrawledItem
from app.domain.ownership import owns_item
from app.domain.sources import UPLOAD
from app.tests.sellers import declare_client_seller, make_seller

pytestmark = pytest.mark.anyio

CRAWLED_URL = "https://m.bunjang.co.kr/products/ownership-1"


# ---------------------------------------------------------------------------
# 순수 규칙
# ---------------------------------------------------------------------------


def test_crawled_items_belong_to_nobody():
    assert not owns_item(account_seller_id=7, item_source="번개장터", item_seller_id=None)
    assert not owns_item(account_seller_id=7, item_source="번개장터", item_seller_id=7)


def test_linked_upload_belongs_to_its_seller_only():
    assert owns_item(account_seller_id=7, item_source=UPLOAD, item_seller_id=7)
    assert not owns_item(account_seller_id=7, item_source=UPLOAD, item_seller_id=8)
    assert not owns_item(account_seller_id=None, item_source=UPLOAD, item_seller_id=8)


def test_nobody_owns_unlinked_or_unassigned():
    """판매자 미지정 계정도, 판매자 없는 매물도 주인 관계가 성립하지 않는다."""
    assert not owns_item(account_seller_id=None, item_source=UPLOAD, item_seller_id=None)
    assert not owns_item(account_seller_id=7, item_source=UPLOAD, item_seller_id=None)
    assert not owns_item(account_seller_id=None, item_source=UPLOAD, item_seller_id=7)


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------


async def _login_client(client):
    res = await client.post(
        "/api/auth/login", json={"username": "client", "password": "client1234"}
    )
    assert res.status_code == 200, res.text


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 30, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def _seed_crawled(session) -> None:
    await repository.upsert_items(
        [
            CrawledItem(
                source="번개장터",
                brand="샤넬",
                title="샤넬 클래식 플랩 미디움",
                price="3,000,000원",
                price_value=3_000_000,
                region="강남구",
                time_text="1시간 전",
                image_url=None,
                url=CRAWLED_URL,
                is_sold=False,
            )
        ],
        session=session,
    )


async def test_csv_cannot_hijack_crawled_listing(client, session, monkeypatch):
    """크롤링 매물 URL 을 CSV 에 적어도 그 매물은 그대로다."""
    await declare_client_seller(session, monkeypatch)
    await _seed_crawled(session)
    await _login_client(client)

    csv = (
        "title,price,url\n"
        f"샤넬 클래식 플랩 미디움 가로채기,10,{CRAWLED_URL}\n"
        "루이비통 네버풀 MM,2000000,https://ex.com/own-1\n"
    )
    res = await client.post(
        "/api/uploads/csv", content=csv.encode(), headers={"Content-Type": "text/csv"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["saved"] == 1
    assert body["skipped"] == 1
    assert any(CRAWLED_URL in e for e in body["errors"])

    await session.rollback()
    row = (
        await session.execute(select(ItemRecord).where(ItemRecord.url == CRAWLED_URL))
    ).scalar_one()
    assert row.source == "번개장터"
    assert row.price_value == 3_000_000


async def test_csv_with_only_foreign_urls_is_400(client, session, monkeypatch):
    await declare_client_seller(session, monkeypatch)
    await _seed_crawled(session)
    await _login_client(client)

    csv = f"title,price,url\n샤넬 클래식 플랩,10,{CRAWLED_URL}\n"
    res = await client.post(
        "/api/uploads/csv", content=csv.encode(), headers={"Content-Type": "text/csv"}
    )
    assert res.status_code == 400
    assert "다른 출처" in res.json()["detail"]


async def test_image_upload_rejects_crawled_item(client, session, monkeypatch):
    await declare_client_seller(session, monkeypatch)
    await _seed_crawled(session)
    await _login_client(client)

    item_id = (
        await session.execute(select(ItemRecord.id).where(ItemRecord.url == CRAWLED_URL))
    ).scalar_one()

    res = await client.put(
        f"/api/uploads/items/{item_id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    assert res.status_code == 403


async def test_image_upload_rejects_other_sellers_item(client, session, monkeypatch):
    """판매자 A 로 선언된 계정은 판매자 B 의 업로드 매물 사진을 못 바꾼다."""
    seller_a = await make_seller(session, "A 상사")
    seller_b = await make_seller(session, "B 상사")

    # B 로 로그인해 올린다.
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_b)
    await _login_client(client)
    csv = "title,price,url\n샤넬 클래식 플랩백 미디움,1000000,https://ex.com/seller-b-1\n"
    res = await client.post(
        "/api/uploads/csv", content=csv.encode(), headers={"Content-Type": "text/csv"}
    )
    assert res.status_code == 200, res.text
    await session.rollback()
    item_id = (
        await session.execute(
            select(ItemRecord.id).where(ItemRecord.url == "https://ex.com/seller-b-1")
        )
    ).scalar_one()

    # 이제 계정이 A 로 선언된다. 판매자 id 는 쿠키가 아니라 매 요청 설정에서 읽으므로
    # 재로그인 없이도 다음 요청부터 A 다. B 의 매물은 남의 것이다.
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_a)
    res = await client.put(
        f"/api/uploads/items/{item_id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    assert res.status_code == 403

    # B 의 CSV 재업로드도 A 는 못 한다.
    res = await client.post(
        "/api/uploads/csv", content=csv.encode(), headers={"Content-Type": "text/csv"}
    )
    assert res.status_code == 400


async def test_unassigned_client_cannot_edit_anything(client, session, monkeypatch):
    """판매자가 선언되지 않은 client(CLIENT_SELLER_ID=0)는 업로드는 되지만 수정은 못 한다."""
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", 0)
    await _login_client(client)

    csv = "title,price,url\n샤넬 클래식 플랩백 미디움,1000000,https://ex.com/unassigned-1\n"
    res = await client.post(
        "/api/uploads/csv", content=csv.encode(), headers={"Content-Type": "text/csv"}
    )
    assert res.status_code == 200, res.text
    await session.rollback()
    item_id = (
        await session.execute(
            select(ItemRecord.id).where(ItemRecord.url == "https://ex.com/unassigned-1")
        )
    ).scalar_one()

    res = await client.put(
        f"/api/uploads/items/{item_id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    assert res.status_code == 403
