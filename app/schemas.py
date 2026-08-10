# schemas.py
"""
API 응답에 쓰이는 Pydantic 모델 정의.
CSV 한 행 = Item, 목록 응답 = ItemListResponse.
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