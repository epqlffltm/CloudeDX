# app/routers/items.py

"""
당근마켓 매물 조회 라우터.
data_loader가 CSV 스냅샷(daangn_with_images.csv)에서 읽어온 결과를
검색/가격 필터 + 페이지네이션해서 반환한다.
main.py에서 app.include_router(router)로 등록한다.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status


router = APIRouter(
    prefix="/items",
    tags=["items"],
)

DATA_PATH = Path("data/crawled_items.json")


def load_items() -> list[dict]:
    if not DATA_PATH.exists():
        return []

    try:
        return json.loads(
            DATA_PATH.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"매물 데이터를 읽을 수 없습니다: {exc}",
        )


@router.get("")
def get_items(
    search: str | None = Query(
        default=None,
        description="제목 검색어",
    ),
    min_price: int | None = Query(
        default=None,
        ge=0,
        description="최소 가격",
    ),
    max_price: int | None = Query(
        default=None,
        ge=0,
        description="최대 가격",
    ),
    region: str | None = Query(
        default=None,
        description="지역 검색",
    ),
    sold: bool | None = Query(
        default=None,
        description="판매완료 여부",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
):
    items = load_items()

    if search:
        keyword = search.casefold()

        items = [
            item
            for item in items
            if keyword in item.get("title", "").casefold()
        ]

    if min_price is not None:
        items = [
            item
            for item in items
            if item.get("price_value") is not None
            and item["price_value"] >= min_price
        ]

    if max_price is not None:
        items = [
            item
            for item in items
            if item.get("price_value") is not None
            and item["price_value"] <= max_price
        ]

    if region:
        keyword = region.casefold()

        items = [
            item
            for item in items
            if keyword in (item.get("region") or "").casefold()
        ]

    if sold is not None:
        items = [
            item
            for item in items
            if item.get("is_sold", False) == sold
        ]

    total = len(items)

    paged_items = items[offset : offset + limit]

    return {
        "total": total,
        "count": len(paged_items),
        "offset": offset,
        "limit": limit,
        "items": paged_items,
    }


@router.get("/{item_index}")
def get_item(item_index: int):
    items = load_items()

    if item_index < 0 or item_index >= len(items):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 매물을 찾을 수 없습니다.",
        )

    return items[item_index]