# app/tests/test_upload_seller_link.py

"""
CSV 업로드 → 판매자 연결 (CLIENT_SELLER_ID).

계정 체계가 단일 client 계정이라 계정↔판매자 정식 연결이 없고, 그 자리를
CLIENT_SELLER_ID 설정이 임시로 메운다. 이 연결이 있어야 화면에서 업로드 매물을
눌렀을 때 판매자 시트가 열린다.

설정값은 uploads 모듈이 임포트 시점에 복사해 가므로, 여기서는 그 모듈의 이름을
monkeypatch 한다 (memo 시절 MEMO_PATH와 같은 수법).
"""

import secrets

from app.db.models import Seller
from app.routers import uploads as uploads_module

CSV = (
    "title,price,url\n"
    "샤넬 클래식 플랩백 미디움,1000000,https://ex.com/link-1\n"
    "루이비통 네버풀 MM,2000000,https://ex.com/link-2\n"
)


async def _login_client(client):
    res = await client.post(
        "/api/auth/login", json={"username": "client", "password": "client1234"}
    )
    assert res.status_code == 200, res.text


async def _upload(client):
    return await client.post(
        "/api/uploads/csv", content=CSV.encode(), headers={"Content-Type": "text/csv"}
    )


async def test_link_disabled_by_default(client, session, monkeypatch):
    """꺼진 상태(0)에서는 아무 연결도 하지 않는다 — 기존 동작 그대로."""
    # 개발자의 .env가 CLIENT_SELLER_ID를 켜 두면 그 값이 테스트까지 새어 들어와
    # 이 테스트가 깨진다. 테스트는 환경에 기대지 말고 검증하려는 값을 직접 박는다.
    monkeypatch.setattr(uploads_module, "CLIENT_SELLER_ID", 0)
    await _login_client(client)

    assert (await _upload(client)).status_code == 200

    body = (await client.get("/api/products")).json()
    assert {item["seller_id"] for item in body["items"]} == {None}


async def test_uploaded_items_link_to_configured_seller(client, session, monkeypatch):
    # conftest는 sellers를 비우지 않으므로(다른 테스트의 판매자가 남는다),
    # 유니크 제약(business_number)과 부딪히지 않게 실행마다 다른 번호를 만든다.
    seller = Seller(
        name="테스트 상사",
        business_number=f"9{secrets.randbelow(100):02d}-{secrets.randbelow(100):02d}-{secrets.randbelow(100000):05d}",
        phone="02-0000-0000",
        has_store=False,
    )
    session.add(seller)
    await session.flush()
    # 롤백 후의 seller.id 접근은 재조회(lazy refresh)를 일으키므로 값만 미리 떠 둔다.
    seller_id = seller.id

    monkeypatch.setattr(uploads_module, "CLIENT_SELLER_ID", seller_id)
    await _login_client(client)

    assert (await _upload(client)).status_code == 200

    # 커밋 누락을 잡는 장치: 미커밋 변경은 여기서 사라진다. 연결이 커밋까지
    # 됐어야 아래 조회에 살아남는다 (실제 앱에서는 세션이 닫히며 롤백된다).
    await session.rollback()

    body = (await client.get("/api/products")).json()
    assert body["total"] == 2
    assert {item["seller_id"] for item in body["items"]} == {seller_id}


async def test_missing_seller_skips_link_but_upload_succeeds(client, session, monkeypatch):
    """
    지정한 판매자가 없으면 연결만 건너뛴다. 업로드까지 실패시키면 설정 실수
    하나가 시연 전체를 막는다 — 경고 로그면 충분하다.
    """
    monkeypatch.setattr(uploads_module, "CLIENT_SELLER_ID", 999_999)
    await _login_client(client)

    res = await _upload(client)

    assert res.status_code == 200
    assert res.json()["saved"] == 2

    body = (await client.get("/api/products")).json()
    assert {item["seller_id"] for item in body["items"]} == {None}
