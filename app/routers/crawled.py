# app/routers/crawled.py

"""
백그라운드 크롤러(app.crawler)가 저장한 최신 JSON 스냅샷을 조회하는 라우터.
정적 CSV를 서빙하는 /items와 달리, 여기는 30분마다 갱신되는 실제 크롤링 결과를 보여준다.
"""

from fastapi import APIRouter, Query, status

from app.crawled_loader import load_crawled_items
from app.schemas import CrawledItemListResponse

router = APIRouter(prefix="/crawled-items", tags=["crawled-items"])


@router.get("", response_model=CrawledItemListResponse, status_code=status.HTTP_200_OK)
def get_crawled_items(
    source: str | None = Query(default=None, description="'당근마켓' 또는 '중고나라'로 필터링"),
    search: str | None = Query(default=None, description="제목에 포함된 검색어"),
    min_price: int | None = Query(default=None, ge=0, description="최소 가격"),
    max_price: int | None = Query(default=None, ge=0, description="최대 가격"),
    limit: int = Query(default=20, ge=1, le=100, description="페이지당 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
):
    """크롤러가 최근에 모은 매물을 사이트/검색어/가격으로 필터링해서 반환."""
    items = load_crawled_items()

    if source:
        items = [i for i in items if i["source"] == source]
    if search:
        items = [i for i in items if search in i["title"]]
    if min_price is not None:
        items = [i for i in items if i["price_value"] is not None and i["price_value"] >= min_price]
    if max_price is not None:
        items = [i for i in items if i["price_value"] is not None and i["price_value"] <= max_price]

    total = len(items)
    page = items[offset : offset + limit]

    return CrawledItemListResponse(total=total, count=len(page), items=page)
