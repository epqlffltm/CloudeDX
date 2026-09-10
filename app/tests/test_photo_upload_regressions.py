# app/tests/test_photo_upload_regressions.py

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app import auth as auth_module
from app.db.models import ItemRecord
from app.tests.sellers import declare_client_seller

pytestmark = pytest.mark.anyio


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 30, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def _login_client(client):
    res = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert res.status_code == 200, res.text


async def test_photo_upload_reaches_storage_for_item_created_by_same_seller(
    client, session, monkeypatch
):
    seller_id = await declare_client_seller(session, monkeypatch)
    await _login_client(client)

    csv = (
        "title,price,url\n"
        "샤넬 클래식 플랩백 미디움,1000000,https://ex.com/photo-own-1\n"
    )
    res = await client.post(
        "/api/uploads/csv",
        content=csv.encode(),
        headers={"Content-Type": "text/csv"},
    )
    assert res.status_code == 200, res.text

    await session.rollback()
    row = (
        await session.execute(
            select(ItemRecord).where(ItemRecord.url == "https://ex.com/photo-own-1")
        )
    ).scalar_one()
    assert row.seller_id == seller_id

    res = await client.put(
        f"/api/uploads/items/{row.id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    # 저장소 설정까지 정상인 테스트 환경이면 200, 저장소를 의도적으로 끈 환경이면 503.
    # 핵심 회귀 조건은 seller 연결 누락으로 403이 되지 않는 것이다.
    assert res.status_code in {200, 503}
    assert res.status_code != 403


async def test_unassigned_client_gets_configuration_error_for_photo(
    client, session, monkeypatch
):
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", 0)
    await _login_client(client)

    res = await client.put(
        "/api/uploads/items/999999/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    assert res.status_code == 409
    assert "판매자가 연결되어 있지 않습니다" in res.json()["detail"]
