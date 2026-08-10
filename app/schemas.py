# schemas.py
"""
API 응답에 쓰이는 Pydantic 모델 정의.
- Item / ItemListResponse: 정적 CSV 스냅샷(data_loader.py) 조회용, CSV 한 행 = Item
- CrawledItemOut / CrawledItemListResponse: 백그라운드 크롤러 JSON(crawled_loader.py) 조회용
"""

from pydantic import BaseModel


class Item(BaseModel):
    id: int
    title: str
    price: str
    price_value: int | None = None
    region: str
    time: str
    image_url: str
    link: str


class ItemListResponse(BaseModel):
    total: int
    count: int
    items: list[Item]


class CrawledItemOut(BaseModel):
    id: int
    source: str
    title: str
    price: str | None = None
    price_value: int | None = None
    region: str | None = None
    time_text: str | None = None
    image_url: str | None = None
    url: str
    is_sold: bool


class CrawledItemListResponse(BaseModel):
    total: int
    count: int
    items: list[CrawledItemOut]