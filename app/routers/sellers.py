# app/routers/sellers.py

"""
입점 판매자 조회.

매물 카드를 눌렀을 때 "이 물건을 누가 파는가"를 보여주기 위한 것이다. 크롤링 매물은
원문 사이트로 나가면 그만이지만, 입점 판매자의 매물은 우리 화면에서 연락처와 매장
위치를 보여줘야 거래가 성립한다.

main.py에서 prefix="/api"를 붙이므로 실제 경로는 /api/sellers/{id} 다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_read_session
from app.db.models import ItemRecord, Seller
from app.schemas.sellers import SellerOut

router = APIRouter(prefix="/sellers", tags=["sellers"])


@router.get(
    "/{seller_id}",
    response_model=SellerOut,
    status_code=status.HTTP_200_OK,
    operation_id="getSeller",
    summary="입점 판매자 정보",
    responses={404: {"description": "해당 판매자를 찾을 수 없습니다."}},
)
async def get_seller(
    seller_id: int,
    session: Annotated[AsyncSession, Depends(get_read_session)],
):
    """
    판매자 한 명의 정보와, 지금 목록에 보이는 매물 건수를 반환한다.

    건수 조건을 목록 API와 맞춘다(is_active, is_usable). "매물 12건"이라고 적어 놓고
    눌렀을 때 8건만 나오면 사용자는 무엇을 믿어야 할지 모른다.
    """
    seller = await session.get(Seller, seller_id)

    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 판매자를 찾을 수 없습니다.",
        )

    item_count = (
        await session.execute(
            select(func.count())
            .select_from(ItemRecord)
            .where(
                ItemRecord.seller_id == seller_id,
                ItemRecord.is_active.is_(True),
                ItemRecord.is_usable.is_(True),
            )
        )
    ).scalar_one()

    return SellerOut(
        id=seller.id,
        name=seller.name,
        business_number=seller.business_number,
        phone=seller.phone,
        has_store=seller.has_store,
        address=seller.address,
        latitude=seller.latitude,
        longitude=seller.longitude,
        description=seller.description,
        photo_url=seller.photo_url,
        item_count=item_count,
    )
