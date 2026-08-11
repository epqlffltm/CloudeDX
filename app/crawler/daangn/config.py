# app/crawler/daangn/config.py

"""
당근마켓 크롤러 설정만 담당.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class DaangnCrawlerConfig:
    base_url: str = "https://www.daangn.com/kr/buy-sell/"
    brand: str = "샤넬"
    keyword_suffix: str = "가방"  # 브랜드명만 검색하면 신발/지갑/향수 등도 섞여서, "가방"을 붙여 좁힌다
    region_code: str | None = None
    headless: bool = True
    timeout_ms: int = 15_000
    scroll_count: int = 6
    scroll_pause_seconds: float = 1.2

    @property
    def query(self) -> str:
        return f"{self.brand} {self.keyword_suffix}".strip()
