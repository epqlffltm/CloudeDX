# app/crawler/models.py

"""
크롤링 결과의 형태를 한 곳에서 정의
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from app.crawler.timeparse import parse_relative_time


@dataclass(slots=True, frozen=True)
class CrawledItem:
    source: str  # 예: "당근마켓", "중고나라"
    brand: str  # 예: "구찌", "에르메스", "샤넬", "루이비통"
    title: str
    price: str | None
    price_value: int | None
    region: str | None
    time_text: str | None  # 사이트 원문 표기. 예: "3시간 전", "끌올 2일 전"
    image_url: str | None
    url: str
    is_sold: bool

    @property
    def posted_at(self) -> datetime | None:
        """
        원글이 올라간 시각. time_text("3시간 전")를 절대 시각으로 환산한 값이고,
        해석할 수 없으면 None이다.

        필드가 아니라 프로퍼티인 이유: 두 크롤러가 각자 계산해서 넣으면 같은 로직이
        두 군데로 갈라진다. 여기서 한 번만 정의하면 시각 표기 규칙이 바뀌어도
        app/crawler/timeparse.py 한 곳만 고치면 된다.

        기준 시각은 이 값을 읽는 순간이다. 수집 직후 DB에 저장하므로 실제 크롤링
        시점과 몇 분 차이지만, 원본 표기 자체가 시간 단위라 오차에 묻힌다.
        """
        return parse_relative_time(self.time_text)

    def to_dict(self) -> dict:
        return asdict(self)
