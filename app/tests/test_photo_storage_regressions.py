# app/tests/test_photo_storage_regressions.py
"""사진 교체의 저장소/DB 순서와 best-effort 정리를 고정한다."""

import io

from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.db.models import ItemRecord
from app.domain import storage
from app.routers import uploads as uploads_router
from app.tests.sellers import declare_client_seller


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), (20, 40, 80)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _login_and_create_item(client, session, monkeypatch, url: str) -> int:
    await declare_client_seller(session, monkeypatch)
    login = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert login.status_code == 200

    csv = f"title,price,url\n샤넬 클래식 플랩백 미디움,1000000,{url}\n"
    uploaded = await client.post(
        "/api/uploads/csv",
        content=csv.encode(),
        headers={"Content-Type": "text/csv"},
    )
    assert uploaded.status_code == 200

    item_id = (
        await session.execute(select(ItemRecord.id).where(ItemRecord.url == url))
    ).scalar_one()
    return item_id


async def test_successful_replace_commits_new_url_then_deletes_previous(
    client, session, monkeypatch
):
    item_id = await _login_and_create_item(
        client, session, monkeypatch, "https://ex.com/photo-replace-ok"
    )

    item = await session.get(ItemRecord, item_id)
    item.image_url = "/uploads/old/previous.jpg"
    await session.commit()

    deleted: list[str] = []
    monkeypatch.setattr(uploads_router, "save_image", lambda data, ext: "new/current.jpg")
    monkeypatch.setattr(uploads_router, "public_url", lambda name: f"/uploads/{name}")
    monkeypatch.setattr(uploads_router, "delete_image", deleted.append)

    response = await client.put(
        f"/api/uploads/items/{item_id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    assert response.status_code == 200
    image_url = (
        await session.execute(select(ItemRecord.image_url).where(ItemRecord.id == item_id))
    ).scalar_one()
    assert image_url == "/uploads/new/current.jpg"
    assert deleted == ["old/previous.jpg"]


async def test_db_commit_failure_deletes_new_object_and_keeps_old_url(
    client, session, monkeypatch
):
    item_id = await _login_and_create_item(
        client, session, monkeypatch, "https://ex.com/photo-replace-db-fail"
    )

    item = await session.get(ItemRecord, item_id)
    item.image_url = "/uploads/old/keep.jpg"
    await session.commit()

    deleted: list[str] = []
    monkeypatch.setattr(uploads_router, "save_image", lambda data, ext: "new/rollback.jpg")
    monkeypatch.setattr(uploads_router, "public_url", lambda name: f"/uploads/{name}")
    monkeypatch.setattr(uploads_router, "delete_image", deleted.append)

    async def fail_commit(self):
        raise OperationalError("UPDATE", {}, Exception("db down"))

    monkeypatch.setattr(type(session), "commit", fail_commit)

    response = await client.put(
        f"/api/uploads/items/{item_id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    assert response.status_code == 503
    image_url = (
        await session.execute(select(ItemRecord.image_url).where(ItemRecord.id == item_id))
    ).scalar_one()
    assert image_url == "/uploads/old/keep.jpg"
    assert deleted == ["new/rollback.jpg"]


def test_local_delete_error_is_best_effort(monkeypatch, caplog):
    class BrokenPath:
        def unlink(self, *, missing_ok: bool):
            assert missing_ok is True
            raise PermissionError("locked")

    monkeypatch.setattr(storage, "S3_BUCKET", "")
    monkeypatch.setattr(storage, "resolve_upload_path", lambda name: BrokenPath())

    storage.delete_image("old/locked.jpg")

    assert "로컬 삭제 실패" in caplog.text
