# app/tests/test_upload_seller_link.py
"""CSV 업로드 → 판매자 연결 및 '내 매물' seller scope 회귀 테스트."""

import secrets

from app import auth as auth_module
from app.db.models import Seller

CSV = (
    "title,price,url\n"
    "샤넬 클래식 플랩백 미디움,1000000,https://ex.com/link-1\n"
    "루이비통 네버풀 MM,2000000,https://ex.com/link-2\n"
)


async def _login_client(client):
    res = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert res.status_code == 200, res.text


async def _upload(client):
    return await client.post(
        "/api/uploads/csv",
        content=CSV.encode(),
        headers={"Content-Type": "text/csv"},
    )


async def _seller(session, name: str) -> int:
    seller = Seller(
        name=name,
        business_number=(
            f"9{secrets.randbelow(100):02d}-"
            f"{secrets.randbelow(100):02d}-"
            f"{secrets.randbelow(100000):05d}"
        ),
        phone="02-0000-0000",
        has_store=False,
    )
    session.add(seller)
    await session.commit()
    return seller.id


async def test_unassigned_client_is_rejected_before_creating_orphan_items(
    client, session, monkeypatch
):
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", 0)
    await _login_client(client)

    res = await _upload(client)

    assert res.status_code == 409
    assert "판매자가 연결되어 있지 않습니다" in res.json()["detail"]

    body = (await client.get("/api/products")).json()
    assert body["total"] == 0


async def test_uploaded_items_link_to_configured_seller(client, session, monkeypatch):
    seller_id = await _seller(session, "테스트 상사")

    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_id)
    await _login_client(client)

    assert (await _upload(client)).status_code == 200

    await session.rollback()

    body = (await client.get("/api/products")).json()
    assert body["total"] == 2
    assert {item["seller_id"] for item in body["items"]} == {seller_id}


async def test_missing_configured_seller_is_rejected(client, session, monkeypatch):
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", 999_999)
    await _login_client(client)

    res = await _upload(client)

    assert res.status_code == 409
    assert "해당하는 판매자가 없습니다" in res.json()["detail"]

    body = (await client.get("/api/products")).json()
    assert body["total"] == 0


async def test_my_items_returns_only_current_sellers_items(client, session, monkeypatch):
    seller_a = await _seller(session, "A 상사")
    seller_b = await _seller(session, "B 상사")

    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_a)
    await _login_client(client)
    csv_a = (
        "title,price,url\n"
        "샤넬 클래식 플랩백 미디움,1000000,https://ex.com/a-only\n"
    )
    assert (
        await client.post(
            "/api/uploads/csv",
            content=csv_a.encode(),
            headers={"Content-Type": "text/csv"},
        )
    ).status_code == 200

    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_b)
    csv_b = (
        "title,price,url\n"
        "루이비통 네버풀 MM,2000000,https://ex.com/b-only\n"
    )
    assert (
        await client.post(
            "/api/uploads/csv",
            content=csv_b.encode(),
            headers={"Content-Type": "text/csv"},
        )
    ).status_code == 200

    mine_b = (await client.get("/api/uploads/items")).json()
    assert mine_b["total"] == 1
    assert mine_b["items"][0]["item_url"] == "https://ex.com/b-only"
    assert mine_b["items"][0]["seller_id"] == seller_b

    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_a)
    mine_a = (await client.get("/api/uploads/items")).json()
    assert mine_a["total"] == 1
    assert mine_a["items"][0]["item_url"] == "https://ex.com/a-only"
    assert mine_a["items"][0]["seller_id"] == seller_a
