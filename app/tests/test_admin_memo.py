# app/tests/test_admin_memo.py

"""
관리자 메모(/api/admin/memo) — 게시판을 걷어낸 자리의 텍스트 한 장.

저장이 파일에서 DB(admin_memo, 한 행짜리 테이블)로 바뀌었지만 API 계약은
그대로다 — 이 파일의 테스트가 파일 시절과 거의 같은 이유이자, 같아야 하는
이유다(화면 코드는 저장소가 바뀐 것을 모른다).

격리는 conftest의 DB 픽스처가 아니라 여기서 직접 한다. conftest의 session
픽스처는 items·crawl_runs만 비우므로, 메모 테이블은 이 파일의 autouse
픽스처가 비운다 — 메모를 아는 것은 이 테스트뿐이라 격리 책임도 여기 둔다.
"""

import pytest_asyncio
from sqlalchemy import text as sql

from app.db.models import AdminMemoRecord  # noqa: F401 — 모델 등록 확인을 겸한다


@pytest_asyncio.fixture(autouse=True)
async def clean_memo(session):
    """모든 테스트가 빈 메모에서 시작한다."""
    await session.execute(sql("TRUNCATE admin_memo"))
    await session.commit()


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


async def test_memo_stays_single_row(client, session):
    """
    몇 번을 저장해도 행은 하나다(id=1 upsert).

    이게 깨지면 GET이 "어느 행이 진짜 메모인가"를 정할 수 없게 된다.
    스키마의 CHECK(id = 1)와 함께 이 성질을 양쪽에서 지킨다.
    """
    await _login(client, "admin", "admin1234")

    await client.put("/api/admin/memo", content=b"one")
    await client.put("/api/admin/memo", content=b"two")
    await client.put("/api/admin/memo", content=b"three")

    count = (await session.execute(sql("SELECT count(*) FROM admin_memo"))).scalar()

    assert count == 1


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
