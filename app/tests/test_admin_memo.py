# app/tests/test_admin_memo.py

"""
관리자 메모(/api/admin/memo) — 게시판을 걷어낸 자리의 텍스트 한 장.

저장이 파일이라 DB 픽스처는 필요 없지만, 경로는 반드시 tmp_path로 바꾼다.
바꾸지 않으면 테스트가 리포의 data/admin_memo.txt 를 실제로 덮어쓴다.
"""

import pytest

from app.routers import memo as memo_module


@pytest.fixture(autouse=True)
def isolated_memo(monkeypatch, tmp_path):
    """모든 테스트가 자기만의 메모 파일을 본다."""
    monkeypatch.setattr(memo_module, "MEMO_PATH", tmp_path / "admin_memo.txt")


async def _login(client, username: str, password: str):
    res = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert res.status_code == 200, res.text


async def test_memo_requires_login(client):
    assert (await client.get("/api/admin/memo")).status_code == 401


async def test_memo_rejects_client_role(client):
    """기업고객은 403 — 401이면 화면이 로그인으로 보내 무한 재로그인이 된다."""
    await _login(client, "client", "client1234")

    assert (await client.get("/api/admin/memo")).status_code == 403


async def test_memo_starts_empty(client):
    await _login(client, "admin", "admin1234")

    body = (await client.get("/api/admin/memo")).json()

    assert body == {"text": "", "updated_at": None}


async def test_memo_roundtrip(client):
    """저장한 그대로 읽힌다 — 한글·개행 포함."""
    await _login(client, "admin", "admin1234")

    text = "인수인계\n- EC2 보안그룹 8000\n- .env.prod 는 Secrets Manager 참고"
    saved = await client.put(
        "/api/admin/memo", content=text.encode(),
        headers={"Content-Type": "text/plain"},
    )

    assert saved.status_code == 200
    assert saved.json()["text"] == text
    assert saved.json()["updated_at"] is not None

    assert (await client.get("/api/admin/memo")).json()["text"] == text


async def test_memo_overwrites_whole_text(client):
    """PUT은 항상 전체 덮어쓰기다 — 이전 내용이 섞여 남지 않는다."""
    await _login(client, "admin", "admin1234")

    await client.put("/api/admin/memo", content="첫 번째".encode())
    await client.put("/api/admin/memo", content="두 번째".encode())

    assert (await client.get("/api/admin/memo")).json()["text"] == "두 번째"


async def test_memo_size_cap(client):
    """64KB를 넘으면 413이고, 기존 메모는 그대로다."""
    await _login(client, "admin", "admin1234")
    await client.put("/api/admin/memo", content=b"keep me")

    res = await client.put("/api/admin/memo", content=b"x" * (64 * 1024 + 1))

    assert res.status_code == 413
    assert (await client.get("/api/admin/memo")).json()["text"] == "keep me"


async def test_memo_rejects_non_utf8(client):
    """저장 전에 거른다 — 저장하고 나면 읽을 때 터지기 때문이다."""
    await _login(client, "admin", "admin1234")

    res = await client.put("/api/admin/memo", content=b"\xff\xfe\x00")

    assert res.status_code == 400
