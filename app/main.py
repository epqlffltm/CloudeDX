# app/main.py

"""
당근마켓 크롤링 결과(CSV)를 조회용 REST API로 제공하는 FastAPI 앱.
DB 없이 CSV를 메모리에 캐싱해서 서빙하는 단순 버전. (uv init 기본 구조 그대로,
app/ 패키지 없이 루트에 파일들을 평평하게 둔 버전)

실행: uv run uvicorn main:app --reload
문서(Swagger UI): http://127.0.0.1:8000/docs
문서(ReDoc):      http://127.0.0.1:8000/redoc
"""

from fastapi import FastAPI, HTTPException, Query, status

from app.data_loader import load_items
from app.schemas import Item, ItemListResponse

app = FastAPI(title="당근마켓 매물 조회 API", version="0.1.0")


@app.get("/items", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
def get_items(
    search: str | None = Query(default=None, description="제목에 포함된 검색어"),
    min_price: int | None = Query(default=None, ge=0, description="최소 가격"),
    max_price: int | None = Query(default=None, ge=0, description="최대 가격"),
    limit: int = Query(default=20, ge=1, le=100, description="페이지당 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
):
    """검색어 / 가격 범위로 필터링한 매물 목록을 페이지네이션해서 반환."""
    items = load_items()

    if search:
        items = [i for i in items if search in i["title"]]
    if min_price is not None:
        items = [i for i in items if i["price_value"] is not None and i["price_value"] >= min_price]
    if max_price is not None:
        items = [i for i in items if i["price_value"] is not None and i["price_value"] <= max_price]

    total = len(items)
    page = items[offset : offset + limit]

    return ItemListResponse(total=total, count=len(page), items=page)


@app.get("/items/{item_id}", response_model=Item, status_code=status.HTTP_200_OK)
def get_item(item_id: int):
    """id(=CSV 행 번호)로 매물 단건 조회."""
    items = load_items()
    for item in items:
        if item["id"] == item_id:
            return item
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="해당 id의 매물을 찾을 수 없습니다.",
    )


@app.get("/", status_code=status.HTTP_200_OK)
def root():
    """헬스 체크 겸 안내용 루트 엔드포인트."""
    return {"message": "당근마켓 매물 조회 API. /docs 에서 API 문서를 확인하세요."}