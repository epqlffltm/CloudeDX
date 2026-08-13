# app/routers/products.py

"""
프론트엔드(ReLuxe)용 상품 API.

`/api/crawled-items`가 우리 도메인 그대로의 매물을 준다면, 여기는 프론트가 기대하는
상품 모양으로 바꿔서 준다. 어댑터를 백엔드에 둔 이유는 프론트 수정량이 적기 때문이고,
나중에 진짜 모델 그룹화를 도입해도 프론트는 그대로 둘 수 있기 때문이다.

두 엔드포인트를 함께 두지 않고 나눈 이유:

    /api/crawled-items  우리 도메인 언어. 매물 단위. 운영·디버깅에 쓴다.
    /api/products       프론트 계약. 상품 단위. 화면이 소비한다.

섞으면 프론트 요구에 맞춰 도메인 모델이 끌려다니게 된다. 실제로 프론트에는
views·likes·grade처럼 우리가 만들 수 없는 필드가 있었는데, 그걸 채우려고
가짜 값을 만들지 않으려면 경계가 필요하다.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository
from app.db.engine import get_session
from app.db.models import ItemRecord
from app.schemas.products import PlatformPrice, ProductListResponse, ProductOut
from app.schemas.requests import CrawledItemFilterParams

router = APIRouter(prefix="/products", tags=["products"])


def _as_utc(moment: datetime) -> datetime:
    """타임존이 없는 값을 UTC로 간주한다. SQLite로 테스트할 때를 대비한 방어."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _listed_days(item: ItemRecord) -> int:
    """
    우리가 이 매물을 관측한 일수.

    "등록 후 며칠"이 아니다. 크롤링을 시작하기 전에 올라온 매물은 실제 등록일을
    알 수 없어서, 정직하게 관측 기준으로 센다. 첫날도 1일로 세도록 +1 한다.
    """
    return (datetime.now(UTC) - _as_utc(item.first_seen_at)).days + 1


def _build_tags(item: ItemRecord) -> list[str]:
    """
    검색 보조 태그. 브랜드·모델·수집처를 담는다.

    제목을 토큰으로 쪼개 넣지 않는 이유는 노이즈가 많아서다 — "정품A급",
    "영수증O" 같은 단어가 태그로 올라오면 화면이 지저분해진다.
    """
    tags = [item.brand]

    if item.model:
        tags.append(item.model)

    tags.append(item.source)

    if item.seller_type == "certified":
        tags.append("인증셀러")

    return tags


def _to_product(item: ItemRecord, drop_rate: float | None = None) -> ProductOut:
    """매물 한 건을 프론트가 기대하는 상품 모양으로 바꾼다."""
    return ProductOut(
        # 나중에 모델 그룹화를 도입하면 "model-샤넬-클래식" 같은 id가 함께 쓰인다.
        # 지금부터 접두어를 붙여 두면 그때 프론트가 구분할 수 있다.
        id=f"item-{item.id}",
        brand=item.brand,
        model_name=item.model,
        korean_name=item.clean_title or item.title,
        thumbnail_url=item.image_url,
        lowest_price=item.price_value,
        platform_prices=[
            PlatformPrice(
                platform_name=item.source,
                price=item.price_value,
                in_stock=item.is_active,
                link_url=item.url,
                seller_type=item.seller_type,
            )
        ],
        tags=_build_tags(item),
        posted_at=item.posted_at,
        listed_days=_listed_days(item),
        price_drop_rate=drop_rate,
    )


@router.get(
    "",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listProducts",
    summary="상품 목록 (프론트엔드용)",
)
async def list_products(
    filters: Annotated[CrawledItemFilterParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    매물을 상품 모양으로 변환해서 반환한다.

    필터는 `/api/crawled-items`와 같은 것을 쓴다. 두 엔드포인트가 다른 조건을
    보기 시작하면 "목록에는 있는데 상품에는 없는" 상황이 생긴다.
    """
    total = await repository.count_items(session, filters)
    rows = await repository.list_items(session, filters)

    return ProductListResponse(
        total=total,
        count=len(rows),
        limit=filters.limit,
        offset=filters.offset,
        has_next=filters.offset + len(rows) < total,
        items=[_to_product(row) for row in rows],
    )


@router.get(
    "/deals",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="listDeals",
    summary="값을 내린 상품",
)
async def list_deals(
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=90, description="조회 기간(일)")] = 7,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """
    최근 값을 내린 상품을 낙폭이 큰 순으로 반환한다.

    이 화면이 단순 목록과 갈리는 지점이다. 중고 거래에서 값을 내렸다는 건 파는 쪽이
    급해졌다는 신호이고, 매물 목록만으로는 알 수 없다.
    """
    drops = await repository.list_price_drops(session, days=days, limit=limit)

    return ProductListResponse(
        total=len(drops),
        count=len(drops),
        limit=limit,
        offset=0,
        has_next=False,
        items=[_to_product(d["item"], drop_rate=d["drop_rate"]) for d in drops],
    )


@router.get(
    "/{product_id}",
    response_model=ProductOut,
    status_code=status.HTTP_200_OK,
    operation_id="getProduct",
    summary="상품 단건",
    responses={404: {"description": "해당 상품을 찾을 수 없습니다."}},
)
async def get_product(
    product_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    상품 단건 조회. id는 목록이 준 `item-{숫자}` 형식이다.

    접두어를 검사하는 이유는 나중에 모델 그룹 id가 생겼을 때 잘못된 종류의 id로
    조회하는 것을 막기 위해서다.
    """
    if not product_id.startswith("item-"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 상품을 찾을 수 없습니다.",
        )

    try:
        item_id = int(product_id.removeprefix("item-"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 상품을 찾을 수 없습니다.",
        ) from None

    item = await repository.get_item(session, item_id)

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 상품을 찾을 수 없습니다.",
        )

    return _to_product(item)