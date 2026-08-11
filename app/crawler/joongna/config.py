# app/crawler/joongna/config.py

"""
중고나라 크롤러 설정만 담당.
daangn/config.py와 동일한 방침 — DB나 FastAPI와 독립적인 설정만 둔다.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class JoongnaCrawlerConfig:
    brand: str = "구찌"
    keyword_suffix: str = "가방"  # 브랜드명만 검색하면 신발/지갑 등도 섞여서, "가방"을 붙여 좁힌다
    category: str = "103"  # 원본 스크립트 기준 여성 가방 카테고리로 추정
    max_pages: int = 5
    headless: bool = True
    timeout_ms: int = 60_000
    scroll_count: int = 3
    scroll_pause_seconds: float = 0.8
    between_page_pause_seconds: float = 1.5

    @property
    def keyword(self) -> str:
        return f"{self.brand} {self.keyword_suffix}".strip()
