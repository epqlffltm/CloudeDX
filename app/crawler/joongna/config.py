# app/crawler/joongna/config.py

"""
중고나라 크롤러 설정만 담당.
daangn/config.py와 동일한 방침 — DB나 FastAPI와 독립적인 설정만 둔다.
"""

from dataclasses import dataclass
from urllib.parse import quote, urlencode

# 받지 않을 리소스 종류. base.EngineConfig의 기본값과 같은 값을 여기 두는 이유는
# 이 모듈이 Playwright에 의존하지 않게 하기 위해서다 — base를 임포트하면 순수 설정
# 파일이 Chromium을 딸고 들어온다. 중복 세 줄이 그 경계보다 싸다.
_BLOCKED_RESOURCES: frozenset[str] = frozenset({"image", "media", "font"})


@dataclass(slots=True)
class JoongnaCrawlerConfig:
    brand: str = "구찌"
    keyword_suffix: str = "가방"  # 브랜드명만 검색하면 다른 품목도 섞여서 서픽스로 좁힌다.
    # 예전 기본값 "103"은 가방 카테고리로 추정된 값이었고, watch/jewelry/apparel/shoes
    # SearchJob에도 그대로 적용돼 검색 계획과 충돌했다. 검증된 카테고리 ID를 명시적으로
    # 아는 호출부만 설정하고, 기본은 키워드 검색 전체 범위로 둔다.
    category: str | None = None
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

    def build_search_url(self, page_num: int) -> str:
        """
        검색 URL을 만든다.

        category가 없으면 category 쿼리 파라미터 자체를 보내지 않는다. 확인되지 않은
        가방 카테고리 ID를 모든 품목 검색에 강제하는 것보다 검색어 서픽스로 범위를
        좁히는 편이 안전하다. 추후 실제 중고나라 카테고리 ID를 검증하면 호출부에서
        category를 명시하면 된다.
        """
        params = {"page": str(page_num)}
        if self.category:
            params["category"] = self.category

        return (
            f"https://web.joongna.com/search/{quote(self.keyword)}"
            f"?{urlencode(params)}"
        )
