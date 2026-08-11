# app/crawler/brands.py

"""
크롤링 대상 명품 브랜드 목록.
한국에서 많이 거래되는 여성 가방 브랜드 기준으로 우선 4개만 둔다.
scheduler.py(자동 스케줄링)와 daangn/joongna의 run.py(수동 CLI)가 공통으로 참조한다.
"""

LUXURY_BRANDS: tuple[str, ...] = ("구찌", "에르메스", "샤넬", "루이비통")
