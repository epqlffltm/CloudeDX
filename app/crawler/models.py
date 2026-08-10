#app/crawler/models.py

"""
크롤링 결과의 형태를 한 곳에서 정의
"""

from dataclasses import asdict, dataclass

@dataclass(slots=True, frozen=True)
class CrawledItem:
    title: str
    price: str | None
    price_value: int | None
    region: str | None
    time_text: str | None
    image_url: str | None
    url: str
    is_sold: bool
    
    def to_dict(self) -> dict:
        return asdict(self)