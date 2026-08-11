#app/crawler/models.py

"""
크롤링 결과의 형태를 한 곳에서 정의
"""

from dataclasses import asdict, dataclass

@dataclass(slots=True, frozen=True)
class CrawledItem:
    source: str  # 예: "당근마켓", "중고나라"
    brand: str  # 예: "구찌", "에르메스", "샤넬", "루이비통"
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