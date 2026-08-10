# app/crawler/joongna/config.py

"""
중고나라 크롤러 설정만 담당.
daangn/config.py와 동일한 방침 — DB나 FastAPI와 독립적인 설정만 둔다.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class JoongnaCrawlerConfig:
    keyword: str = "구찌"
    category: str = "103"
    max_pages: int = 5
    headless: bool = True
    timeout_ms: int = 60_000
    scroll_count: int = 3
    scroll_pause_seconds: float = 0.8
    between_page_pause_seconds: float = 1.5
