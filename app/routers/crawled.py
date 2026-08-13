# app/routers/crawled.py

"""
매물 데이터를 JSON으로 제공하는 API 라우터.

같은 데이터를 사람이 보는 화면으로 그리는 건 app/routers/web.py(게시판)이고, 여기는
프론트엔드가 소비할 API다. 둘 다 같은 app.db.repository를 호출하므로 필터/정렬 동작이
갈라지지 않는다.

main.py에서 prefix="/api"를 붙여 등록하므로 실제 경로는 /api/crawled-items다.
화면 경로(/board)와 API 경로를 분리해 두면 나중에 프론트를 별도 서버로 띄우거나
리버스 프록시에서 /api만 백엔드로 넘기는 구성이 쉬워진다.

각 엔드포인트에 operation_id를 명시한 이유: OpenAPI 스키마에서 타입스크립트 클라이언트를
생성할 때 이 값이 함수 이름이 된다. 지정하지 않으면 경로와 메서드를 조합한 긴 이름이
자동 생성되고, 라우터 경로를 바꾸는 순간 프론트의 함수 이름까지 따라 바뀐다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository
from app.db.engine import get_session
from app.schemas.requests import CrawledItemFilterParams
from app.schemas.responses import (
    CrawledItemListResponse,
    CrawledItemOut,
    PriceDrop,
    PriceDropListResponse,
    PriceHistoryResponse,
    PricePoint,
)

router = APIRouter(prefix="/crawled-items", tags=["crawled-items"])


@router.get(
    "",
    response_model=CrawledItemListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listCrawledItems",
    summary="매물 목록 조회",
)
async def get_crawled_items(
    filters: Annotated[CrawledItemFilterParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    저장된 매물을 수집처/브랜드/검색어/가격/판매상태로 필터링해서 반환한다.

    정렬은 등록 시각 내림차순(최근 글이 먼저)으로 고정이다. 등록 시각을 구하지 못한
    매물은 수집 시각으로 대체해서 정렬한다.
    """
    total = await repository.count_items(session, filters)
    rows = await repository.list_items(session, filters)

    return CrawledItemListResponse(
        total=total,
        count=len(rows),
        limit=filters.limit,
        offset=filters.offset,
        has_next=filters.offset + len(rows) < total,
        items=[CrawledItemOut.model_validate(row) for row in rows],
    )


# 경로 순서에 주의. FastAPI는 등록 순서대로 매칭하므로 "/{item_id}" 가 먼저 오면
# "/price-drops" 요청이 item_id="price-drops" 로 해석돼 422가 난다.
# 고정 경로를 항상 경로 변수보다 먼저 등록한다.
@router.get(
    "/price-drops",
    response_model=PriceDropListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listPriceDrops",
    summary="값을 내린 매물",
)
async def get_price_drops(
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=90, description="조회 기간(일)")] = 7,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """
    최근 값을 내린 매물을 낙폭이 큰 순으로 반환한다.

    중고 거래에서 값을 내렸다는 건 파는 쪽이 급해졌다는 신호다. 매물 목록만으로는
    알 수 없고 가격 이력이 있어야 나오는 정보다.
    """
    drops = await repository.list_price_drops(session, days=days, limit=limit)

    return PriceDropListResponse(
        days=days,
        count=len(drops),
        items=[
            PriceDrop(
                item=CrawledItemOut.model_validate(d["item"]),
                old_price=d["old_price"],
                new_price=d["new_price"],
                drop_amount=d["drop_amount"],
                drop_rate=d["drop_rate"],
            )
            for d in drops
        ],
    )


@router.get(
    "/{item_id}",
    response_model=CrawledItemOut,
    status_code=status.HTTP_200_OK,
    operation_id="getCrawledItem",
    summary="매물 단건 조회",
    responses={404: {"description": "해당 id의 매물을 찾을 수 없습니다."}},
)
async def get_crawled_item(
    item_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """id 기준 단건 조회. id는 크롤링이 다시 돌아도 바뀌지 않는다."""
    row = await repository.get_item(session, item_id)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 id의 매물을 찾을 수 없습니다.",
        )

    return CrawledItemOut.model_validate(row)


@router.get(
    "/{item_id}/price-history",
    response_model=PriceHistoryResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getPriceHistory",
    summary="매물 가격 이력",
    responses={404: {"description": "해당 id의 매물을 찾을 수 없습니다."}},
)
async def get_price_history(
    item_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    가격이 바뀐 시점들을 오래된 순으로 반환한다.

    매 관측이 아니라 변화 시점만 담긴다 — 30분마다 쌓으면 대부분이 "어제와 같음"
    이라 정보가 없고 양만 늘어난다.
    """
    if await repository.get_item(session, item_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 id의 매물을 찾을 수 없습니다.",
        )

    records = await repository.get_price_history(session, item_id)
    prices = [r.price_value for r in records]

    return PriceHistoryResponse(
        item_id=item_id,
        points=[PricePoint.model_validate(r) for r in records],
        lowest=min(prices) if prices else None,
        highest=max(prices) if prices else None,
        total_change=(prices[-1] - prices[0]) if len(prices) >= 2 else None,
    )