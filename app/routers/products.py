# app/routers/products.py

"""
프론트엔드(ReLuxe)용 매물 API.

`/api/crawled-items`가 우리 도메인 그대로의 매물(운영·디버깅용 전체 필드)을 준다면,
여기는 화면이 소비하는 최소 계약만 내려준다. 경계를 두는 이유는 그대로다 — 프론트
요구에 맞춰 도메인 모델이 끌려다니지 않게 하고, 운영 필드(reject_reason,
missing_count 등)가 화면 계약에 새어 나가지 않게 한다.

경로는 /api/products를 유지한다. 응답 단위가 상품에서 매물로 바뀌었지만 URL까지
바꾸면 백엔드 배포와 프론트 배포를 묶어야 한다. 이름의 정확성보다 배포 독립성이
크다고 봤다. 코드 안의 이름(ListingOut)은 실제 단위를 따른다.

필터는 `/api/crawled-items`와 같은 CrawledItemFilterParams를 쓴다. 두 엔드포인트가
다른 조건을 보기 시작하면 "목록에는 있는데 화면에는 없는" 상황이 생긴다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import clicks, repository
from app.db.engine import get_read_session
from app.db.models import ItemRecord
from app.schemas.products import ListingListResponse, ListingOut
from app.schemas.requests import CrawledItemFilterParams

router = APIRouter(prefix="/products", tags=["products"])


def _to_listing(item: ItemRecord) -> ListingOut:
    """매물 한 건을 프론트 계약으로 바꾼다. 계산 없이 컬럼을 고르기만 한다."""
    return ListingOut(
        id=item.id,
        source=item.source,
        # 정제 제목이 있으면 그쪽. 검색용 브랜드 나열 꼬리가 붙은 원제목을 카드에
        # 올리면 서른 자짜리 브랜드 사전이 화면을 덮는다.
        title=item.clean_title or item.title,
        brand=item.brand,
        category=item.category,
        price=item.price_value,
        image_url=item.image_url,
        item_url=item.url,
        seller_id=item.seller_id,
        is_authenticated=item.is_authenticated,
    )


@router.get(
    "",
    response_model=ListingListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listListings",
    summary="매물 목록 (프론트엔드용)",
)
async def list_listings(
    filters: Annotated[CrawledItemFilterParams, Query()],
    session: Annotated[AsyncSession, Depends(get_read_session)],
):
    """
    매물을 프론트 계약(ListingOut)으로 반환한다.

    정렬은 최신 발견 순 고정이다. 등록 시각을 주는 수집처는 그 값을, 안 주는
    수집처는 첫 수집 시각을 기준으로 한다 (repository._order_key 참고).
    """
    total = await repository.count_items(session, filters)
    rows = await repository.list_items(session, filters)

    return ListingListResponse(
        total=total,
        count=len(rows),
        limit=filters.limit,
        offset=filters.offset,
        has_next=filters.offset + len(rows) < total,
        items=[_to_listing(row) for row in rows],
    )


# /{item_id}보다 **먼저** 등록해야 한다. 뒤에 두면 "popular"가 item_id 자리로
# 매칭돼 정수 변환 실패(422)가 난다. FastAPI는 등록 순서대로 경로를 본다.
@router.get(
    "/popular",
    response_model=ListingListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listPopularListings",
    summary="인기 매물 (대문 레일용)",
)
async def list_popular_listings(
    session: Annotated[AsyncSession, Depends(get_read_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
):
    """
    클릭이 많은 순. 직접등록 매물이 앞이고, 모자라면 크롤링 매물이 채운다
    (app/db/clicks.list_popular). 응답 모양은 목록과 같다 — 화면이 카드를 그리는
    코드를 공유하기 위해서다. 페이지네이션은 없으므로 offset=0, has_next=false 고정.

    클릭 수 자체는 내려주지 않는다. 정렬 결과만 계약이다.
    """
    rows = await clicks.list_popular(session, limit)

    return ListingListResponse(
        total=len(rows),
        count=len(rows),
        limit=limit,
        offset=0,
        has_next=False,
        items=[_to_listing(row) for row in rows],
    )


@router.get(
    "/{item_id}",
    response_model=ListingOut,
    status_code=status.HTTP_200_OK,
    operation_id="getListing",
    summary="매물 단건",
    responses={404: {"description": "해당 매물을 찾을 수 없습니다."}},
)
async def get_listing(
    item_id: int,
    session: Annotated[AsyncSession, Depends(get_read_session)],
):
    """
    매물 단건 조회. id는 정수 PK다.

    예전에는 "item-{숫자}" 문자열이었다 — 모델 그룹 id("model-샤넬-클래식")와 함께
    쓸 자리를 잡아둔 것인데, 그룹핑을 포기하면서 접두어의 존재 이유가 사라졌다.
    프론트가 id에서 숫자를 파싱해 정렬하던 관행도 같이 죽었으므로 정수로 단순화한다.
    """
    item = await repository.get_item(session, item_id)

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 매물을 찾을 수 없습니다.",
        )

    return _to_listing(item)
