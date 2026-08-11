# app/routers/crawled.py

"""
DB(items 테이블)에 저장된 크롤링 결과를 조회하는 라우터.
정적 CSV를 서빙하는 /items와 달리, 여기는 크롤러가 upsert한 실제 최신 데이터를 보여준다.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import ItemRecord
from app.schemas import CrawledItemListResponse, CrawledItemOut

router = APIRouter(prefix="/crawled-items", tags=["crawled-items"])


@router.get("", response_model=CrawledItemListResponse, status_code=status.HTTP_200_OK)
async def get_crawled_items(
    source: str | None = Query(default=None, description="'당근마켓' 또는 '중고나라'로 필터링"),
    brand: str | None = Query(default=None, description="'구찌'/'에르메스'/'샤넬'/'루이비통' 등으로 필터링"),
    search: str | None = Query(default=None, description="제목에 포함된 검색어"),
    min_price: int | None = Query(default=None, ge=0, description="최소 가격"),
    max_price: int | None = Query(default=None, ge=0, description="최대 가격"),
    limit: int = Query(default=20, ge=1, le=100, description="페이지당 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
    session: AsyncSession = Depends(get_session),
):
    """DB에 저장된 매물을 사이트/브랜드/검색어/가격으로 필터링해서 반환."""
    stmt = select(ItemRecord)

    if source:
        stmt = stmt.where(ItemRecord.source == source)
    if brand:
        stmt = stmt.where(ItemRecord.brand == brand)
    if search:
        stmt = stmt.where(ItemRecord.title.ilike(f"%{search}%"))
    if min_price is not None:
        stmt = stmt.where(ItemRecord.price_value >= min_price)
    if max_price is not None:
        stmt = stmt.where(ItemRecord.price_value <= max_price)

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    stmt = stmt.order_by(ItemRecord.last_seen_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()

    return CrawledItemListResponse(
        total=total,
        count=len(rows),
        items=[CrawledItemOut.model_validate(row) for row in rows],
    )


@router.get(
    "/{item_id}",
    response_model=CrawledItemOut,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "해당 id의 매물을 찾을 수 없습니다."}},
)
async def get_crawled_item(item_id: int, session: AsyncSession = Depends(get_session)):
    """DB의 실제 PK 기준 단건 조회. (id는 이제 요청마다 매겨지는 게 아니라 영구적인 값이다.)"""
    row = await session.get(ItemRecord, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 id의 매물을 찾을 수 없습니다.")

    return CrawledItemOut.model_validate(row)
