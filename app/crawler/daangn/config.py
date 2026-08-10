# app/crawler/daangn/config.py

"""
당근마켓 크롤러 설정만 담당.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class DaangnCrawlerConfig:
    base_url: str = "https://www.daangn.com/kr/buy-sell/"
    query: str = "아이폰"
    region_code: str | None = None
    headless: bool = True
    timeout_ms: int = 15_000
    scroll_count: int = 6
    scroll_pause_seconds: float = 1.2
