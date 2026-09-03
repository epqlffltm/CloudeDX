# app/tests/sellers.py

"""
테스트용 판매자 도우미.

업로드 매물을 고치려면 계정이 그 매물의 판매자여야 한다(app/domain/ownership.py).
그래서 "client 로 로그인해서 사진을 올린다"류의 테스트는 먼저 판매자를 하나 만들고
client 계정을 그 판매자로 선언해야 한다. 그 두 줄을 여기 모은다.
"""

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app import auth as auth_module
from app.db.models import Seller


def random_business_number() -> str:
    # conftest 는 sellers 를 비우지 않는다. 유니크 제약과 부딪히지 않게 매번 다르게.
    return (
        f"7{secrets.randbelow(100):02d}-{secrets.randbelow(100):02d}-"
        f"{secrets.randbelow(100000):05d}"
    )


async def make_seller(session: AsyncSession, name: str = "테스트 상사") -> int:
    seller = Seller(
        name=name,
        business_number=random_business_number(),
        phone="02-0000-0000",
        has_store=False,
    )
    session.add(seller)
    await session.commit()
    return seller.id


async def declare_client_seller(session: AsyncSession, monkeypatch, name: str = "테스트 상사") -> int:
    """판매자를 만들고, client 계정이 그 판매자라고 선언한다. **로그인 전에** 불러야 한다."""
    seller_id = await make_seller(session, name)
    monkeypatch.setattr(auth_module, "CLIENT_SELLER_ID", seller_id)
    return seller_id
