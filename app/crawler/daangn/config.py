# app/crawler/daangn/config.py

"""
당근마켓 크롤러 설정만 담당.
"""

from dataclasses import dataclass

# 받지 않을 리소스 종류. base.EngineConfig의 기본값과 같은 값을 여기 두는 이유는
# 이 모듈이 Playwright에 의존하지 않게 하기 위해서다 — base를 임포트하면 순수 설정
# 파일이 Chromium을 딸고 들어온다. 중복 세 줄이 그 경계보다 싸다.
_BLOCKED_RESOURCES: frozenset[str] = frozenset({"image", "media", "font"})


@dataclass(slots=True)
class DaangnCrawlerConfig:
    base_url: str = "https://www.daangn.com/kr/buy-sell/"
    brand: str = "샤넬"
    keyword_suffix: str = "가방"  # 브랜드명만 검색하면 신발/지갑/향수 등도 섞여서, "가방"을 붙여 좁힌다
    region_code: str | None = None
    headless: bool = True
    timeout_ms: int = 15_000
    scroll_count: int = 6
    # 리소스 차단으로 페이지가 가벼워진 만큼 줄였다(1.2 -> 0.7). 스크롤 한 번에
    # 새 카드가 붙는 시간이라, 너무 짧으면 바닥에 도달하지 않았는데 높이가 그대로라고
    # 오판할 수 있다. 수집 건수가 눈에 띄게 줄면 되돌린다.
    scroll_pause_seconds: float = 0.7

    # 카드가 그려질 때까지 기다리는 한도. 초과해도 예외가 아니라 "0건"으로 넘어간다.
    card_wait_ms: int = 6_000

    # 받지 않을 리소스. 당근마켓 이미지 URL이 안 잡히는 기존 이슈가 있어, 이미지
    # 차단이 그 증상을 악화시키면 여기서 "image"만 빼면 된다:
    #     blocked_resources = frozenset({"media", "font"})
    blocked_resources: frozenset[str] = _BLOCKED_RESOURCES

    @property
    def query(self) -> str:
        return f"{self.brand} {self.keyword_suffix}".strip()
