# app/crawler/joongna/config.py

"""
중고나라 크롤러 설정만 담당.
daangn/config.py와 동일한 방침 — DB나 FastAPI와 독립적인 설정만 둔다.
"""

from dataclasses import dataclass

# 받지 않을 리소스 종류. base.EngineConfig의 기본값과 같은 값을 여기 두는 이유는
# 이 모듈이 Playwright에 의존하지 않게 하기 위해서다 — base를 임포트하면 순수 설정
# 파일이 Chromium을 딸고 들어온다. 중복 세 줄이 그 경계보다 싸다.
_BLOCKED_RESOURCES: frozenset[str] = frozenset({"image", "media", "font"})


@dataclass(slots=True)
class JoongnaCrawlerConfig:
    brand: str = "구찌"
    keyword_suffix: str = "가방"  # 브랜드명만 검색하면 신발/지갑 등도 섞여서, "가방"을 붙여 좁힌다
    category: str = "103"  # 원본 스크립트 기준 여성 가방 카테고리로 추정
    max_pages: int = 5
    headless: bool = True
    timeout_ms: int = 60_000
    scroll_count: int = 3
    scroll_pause_seconds: float = 0.5
    between_page_pause_seconds: float = 1.5

    # 카드가 그려질 때까지 기다리는 한도. 고정 sleep(2초)을 대신한다.
    # 초과해도 예외가 아니라 "0건"으로 넘어간다.
    card_wait_ms: int = 6_000

    blocked_resources: frozenset[str] = _BLOCKED_RESOURCES

    @property
    def keyword(self) -> str:
        return f"{self.brand} {self.keyword_suffix}".strip()
