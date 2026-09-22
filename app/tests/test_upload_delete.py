# app/tests/test_upload_delete.py

"""
매물 내리기(DELETE /api/uploads/items/{id}) 테스트.

확인하는 것은 네 가지다.
1. 내린 매물은 '내 매물'과 공개 목록에서 모두 사라진다
2. 행은 남는다 — 같은 url 을 다시 올렸을 때 되살아나야 하므로
3. 남의 매물은 403, 없는 매물은 404
4. 두 번 눌러도 200 (화면이 두 번 클릭을 에러로 만들지 않는다)
"""

from sqlalchemy import select

from app import auth as auth_module
from app.db.models import ItemRecord
from app.tests.sellers import declare_client_seller, make_seller

CSV = (
    "title,price,url\n"
    "샤넬 클래식 플랩백 미디움,1000000,https://ex.com/del-1\n"
    "루이비통 네버풀 MM,2000000,https://ex.com/del-2\n"
)


async def _login_client(client):
    res = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert res.status_code == 200, res.text


async def _upload_two(client):
    res = await client.post(
        "/api/uploads/csv",
        content=CSV.encode(),
        headers={"Content-Type": "text/csv"},
    )
    assert res.status_code == 200, res.text

    items = (await client.get("/api/uploads/items")).json()["items"]
    assert len(items) == 2
    return items


async def test_deleted_item_disappears_but_row_remains(client, session, monkeypatch):
    await declare_client_seller(session, monkeypatch)
    await _login_client(client)
    items = await _upload_two(client)
    target = items[0]

    res = await client.delete(f"/api/uploads/items/{target['id']}")

    assert res.status_code == 200, res.text
    assert res.json()["item_id"] == target["id"]

    # '내 매물'에서 사라진다
    mine = (await client.get("/api/uploads/items")).json()
    assert mine["total"] == 1
    assert [it["id"] for it in mine["items"]] == [items[1]["id"]]

    # 공개 목록에서도 사라진다
    public = (await client.get("/api/products")).json()
    assert target["id"] not in [it["id"] for it in public["items"]]

    # 행은 남아 있고 is_active 만 내려간다
    row = (
        await session.execute(
            select(ItemRecord).where(ItemRecord.id == target["id"])
        )
    ).scalar_one()
    assert row.is_active is False


async def test_delete_is_idempotent(client, session, monkeypatch):
    await declare_client_seller(session, monkeypatch)
    await _login_client(client)
    items = await _upload_two(client)
    item_id = items[0]["id"]

    first = await client.delete(f"/api/uploads/items/{item_id}")
    second = await client.delete(f"/api/uploads/items/{item_id}")

    assert first.status_code == 200
    assert second.status_code == 200, second.text


async def test_other_sellers_item_is_forbidden(client, session, monkeypatch):
    await declare_client_seller(session, monkeypatch, "A 상사")
    await _login_client(client)
    items = await _upload_two(client)
    item_id = items[0]["id"]

    # 같은 계정이 이제 다른 판매자라고 선언되면 남의 매물이 된다.
    other = await make_seller(session, "B 상사")
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", other)
    await _login_client(client)

    res = await client.delete(f"/api/uploads/items/{item_id}")

    assert res.status_code == 403


async def test_missing_item_is_404(client, session, monkeypatch):
    await declare_client_seller(session, monkeypatch)
    await _login_client(client)

    res = await client.delete("/api/uploads/items/999999")

    assert res.status_code == 404
