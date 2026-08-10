#app/crawler/config.py

"""
크롤러 설정만 담당
DB나 FastAPI와는 독립적인 설정만 둔다.
이후 환경변수 기반 설정이 필요해지면 이 파일만 확장하면 된다.
"""


from dataclasses import dataclass

@dataclass(slots=True)
class CrawlerConfig:
    base_url: str = "https://www.daangn.com/kr/buy-sell/"
    timeout_seconds: int = 15
    scroll_count: int = 6
    scroll_pause_seconds: float = 1.2
    headless: bool = True
    window_width: int = 1440
    window_height: int = 1200