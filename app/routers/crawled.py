# app/routers/crawled.py

"""
DB(items 테이블)에 저장된 크롤링 결과를 JSON으로 제공하는 라우터.

같은 데이터를 사람이 보는 화면으로 그리는 건 app/routers/web.py(게시판)이고,
여기는 나중에 프론트엔드를 따로 붙일 때 쓰는 JSON API다. 둘 다 같은
app.db.repository를 호출하므로 필터/정렬 동작이 갈라지지 않는다.

라우터는 얇게 유지한다 — 요청 검증은 app.schemas.requests가, 실제 쿼리는
repository가 담당하고, 여기서는 둘을 이어붙이고 404 같은 HTTP 관심사만 처리한다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository
from app.db.engine import get_session
from app.schemas.requests import CrawledItemFilterParams
from app.schemas.responses import CrawledItemListResponse, CrawledItemOut

router = APIRouter(prefix="/crawled-items", tags=["crawled-items"])


@router.get(
    "",
    response_model=CrawledItemListResponse,
    status_code=status.HTTP_200_OK,
    summary="매물 목록 조회",
)
async def get_crawled_items(
    filters: Annotated[CrawledItemFilterParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """DB에 저장된 매물을 수집처/브랜드/검색어/가격/판매상태로 필터링해서 반환한다."""
    total = await repository.count_items(session, filters)
    rows = await repository.list_items(session, filters)

    return CrawledItemListResponse(
        total=total,
        count=len(rows),
        limit=filters.limit,
        offset=filters.offset,
        items=[CrawledItemOut.model_validate(row) for row in rows],
    )


@router.get(
    "/{item_id}",
    response_model=CrawledItemOut,
    status_code=status.HTTP_200_OK,
    summary="매물 단건 조회",
    responses={404: {"description": "해당 id의 매물을 찾을 수 없습니다."}},
)
async def get_crawled_item(
    item_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """DB의 실제 PK 기준 단건 조회. id는 크롤링이 다시 돌아도 바뀌지 않는다."""
    row = await repository.get_item(session, item_id)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 id의 매물을 찾을 수 없습니다.",
        )

    return CrawledItemOut.model_validate(row)
