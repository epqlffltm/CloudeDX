# app/domain/models.py

"""
크롤링 결과의 형태를 한 곳에서 정의
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from app.domain.timeparse import parse_relative_time


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
    # 판매자 유형. 배지 체계가 있는 사이트에서만 채워지고, 당근마켓은 항상 None이다.
    # None은 "개인 판매자"가 아니라 "판정할 수 없음"을 뜻한다.
    seller_type: str | None = None

    # 정품 인증 여부. 크롤러는 이 값을 채우지 않는다(기본 False). 기업고객이
    # 올린 CSV의 인증 컬럼에서만 True가 들어오고, 실제 저장 여부는
    # repository가 source까지 함께 보고 결정한다.
    is_authenticated: bool = False

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