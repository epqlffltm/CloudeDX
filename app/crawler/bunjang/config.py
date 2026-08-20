# app/crawler/bunjang/config.py

"""
번개장터 크롤러 설정만 담당.
daangn/joongna의 config와 동일한 방침 — DB나 FastAPI와 독립적인 설정만 둔다.
"""

from dataclasses import dataclass

# 번개장터 검색 API의 브랜드 필터 ID. 팀에서 실측으로 확인한 값만 등록한다 —
# 지어내지 않는다. 여기 없는 브랜드는 키워드 검색만으로 동작하고, 그래도
# 수집은 된다(정밀도만 떨어진다). 시계·주얼리 브랜드 ID는 실측 후 채운다.
BUNJANG_BRAND_IDS: dict[str, str] = {
    "구찌": "23",
    "루이비통": "16",
    "샤넬": "28",
    "프라다": "20",
    "디올": "31",
    "에르메스": "34",
    "생로랑": "40",  # 입생로랑과 같은 ID — 우리 정규명은 생로랑 하나다
    "보테가": "54",
    "발렌시아가": "52",
    "셀린느": "45",
}


@dataclass(slots=True)
class BunjangCrawlerConfig:
    brand: str = "구찌"
    keyword_suffix: str = "가방"
    max_pages: int = 3
    timeout_seconds: float = 10.0
    between_page_pause_seconds: float = 0.8  # 원본 스크립트의 검증된 간격

    @property
    def keyword(self) -> str:
        # 원본 스크립트는 "구찌가방"처럼 붙여 검색했지만, 번개장터 검색은
        # 토큰 단위라 공백 유무가 결과를 가르지 않는다 — 우리 표준(공백)을 따른다.
        return f"{self.brand} {self.keyword_suffix}".strip()

    @property
    def brand_id(self) -> str:
        return BUNJANG_BRAND_IDS.get(self.brand, "")
