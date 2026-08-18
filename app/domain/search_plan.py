# app/domain/search_plan.py

"""
크롤러의 검색 계획: 카테고리마다 어느 브랜드를 어떤 서픽스로 검색하는가.

카테고리별로 유효한 브랜드가 다르다 — "롤렉스 가방"이나 "고야드 시계"를 검색할
이유가 없다. 그래서 브랜드 목록을 카테고리 축으로 나눈다. 가방 브랜드는
brands.py의 LUXURY_BRANDS를 그대로 쓴다 (거기가 가방 수집의 정본이다).

서픽스는 v1 가설이다. "까르띠에 주얼리"보다 "까르띠에 팔찌"가 검색이 잘 될 수도
있는데, 실측 없이 늘리면 크롤 볼륨만 커진다. 실크롤을 몇 라운드 돌린 뒤
카테고리별 유입량을 보고 조정한다.

**크롤 볼륨 주의**: 이 계획은 소스당 32잡, 두 소스 64잡이다. 기존(브랜드 4 ×
2소스 = 8잡)의 8배다. CRAWL_INTERVAL_MINUTES를 30 → 60으로 올리는 것을
권장하고, 중고나라는 JOONGNA_PAGES_PER_BRAND로 잡당 페이지 수를 조절할 수 있다.
"""

from app.domain.brands import LUXURY_BRANDS
from app.domain.collection import SearchJob

# 카테고리 → (브랜드들, 검색 서픽스). 잡 수 = 브랜드 수 × 1.
_CATEGORY_SEARCHES: dict[str, tuple[tuple[str, ...], str]] = {
    "bag": (LUXURY_BRANDS, "가방"),
    "watch": (("롤렉스", "오메가", "까르띠에", "불가리", "샤넬"), "시계"),
    "jewelry": (("까르띠에", "티파니", "불가리", "반클리프", "샤넬"), "주얼리"),
    "apparel": (("구찌", "버버리", "프라다", "생로랑", "디올"), "자켓"),
    "shoes": (("구찌", "프라다", "발렌시아가", "생로랑", "에르메스"), "신발"),
}

SEARCH_PLAN: tuple[SearchJob, ...] = tuple(
    SearchJob(brand=brand, category=category, suffix=suffix)
    for category, (brands, suffix) in _CATEGORY_SEARCHES.items()
    for brand in brands
)
