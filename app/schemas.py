# schemas.py
"""
API 응답에 쓰이는 Pydantic 모델 정의.
- Item / ItemListResponse: 정적 CSV 스냅샷(data_loader.py) 조회용, CSV 한 행 = Item
- CrawledItemOut / CrawledItemListResponse: DB(items 테이블, app.db.models.ItemRecord) 조회용
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    # ItemRecord(SQLAlchemy ORM 객체)를 그대로 넣어도 필드를 읽어 직렬화할 수 있게 한다.
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    brand: str
    title: str
    price: str | None = None
    price_value: int | None = None
    region: str | None = None
    time_text: str | None = None
    image_url: str | None = None
    url: str
    is_sold: bool
    first_seen_at: datetime
    last_seen_at: datetime


class CrawledItemListResponse(BaseModel):
    total: int
    count: int
    items: list[CrawledItemOut]