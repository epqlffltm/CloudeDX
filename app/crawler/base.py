# app/crawler/base.py

"""
사이트 공통 크롤링 엔진 (Playwright 기반, 완전 비동기).

당근마켓/중고나라 모두 "브라우저 실행 -> 검색 결과 스크롤 -> 카드 링크 훑어서
href/텍스트/이미지 추출 -> 사이트별 파서에 넘기기" 흐름이 동일해서 여기 하나로 모았다.
사이트마다 다른 부분(URL 생성, CSS 셀렉터, 텍스트 -> dict 파싱)은 각 사이트의
crawler.py에서 콜백으로 주입한다.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.domain.parse_health import ParseHealth

logger = logging.getLogger(__name__)

# 브라우저 식별 문자열.
#
# 자동화를 숨기려는 목적이 아니다. Playwright 기본값은 "HeadlessChrome"을 포함해서
# 일부 사이트가 렌더링 자체를 다르게 하거나 빈 페이지를 주는데, 그러면 셀렉터가
# 아무것도 못 잡아 원인 파악이 어려워진다. 우리가 보는 화면과 실제 사용자가 보는
# 화면을 일치시키는 것이 목적이다.
#
# navigator.webdriver 를 지우는 스크립트가 예전에 여기 있었는데 제거했다. 그건
# 봇 감지를 우회하려는 코드이고, 사이트가 자동화를 거절하겠다는 의사 표시를
# 기술적으로 무력화하는 셈이라 수집 도구가 넘지 않아야 할 선이다.
#
# 버전을 고정하지 않고 실제 실행 중인 Chromium에서 읽는다. 고정하면 시간이 갈수록
# 실제 브라우저와 어긋나서 오히려 특이한 지문이 된다 — "Chrome/120인데 최신 기능을
# 쓰는 브라우저"는 흔치 않다. 아래 문자열은 버전을 못 읽었을 때의 대체값이다.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# 받지 않을 리소스 종류.
#
# 카드에서 읽는 것은 href, 텍스트, img의 src **속성**뿐이다. 이미지 바이트를 실제로
# 내려받을 필요가 없고, 폰트와 동영상도 마찬가지다. 요청을 끊으면 페이지가 준비되는
# 시점이 크게 앞당겨진다 — 검색 결과 한 페이지에 썸네일이 수십 장씩 붙는다.
#
# stylesheet는 일부러 넣지 않았다. scroll_page가 document.body.scrollHeight로 바닥을
# 판단하는데, CSS가 없으면 레이아웃이 무너져 그 값이 엉뚱해진다. 스크롤 종료 판정이
# 어긋나면 "끝까지 봤다"는 확신이 깨지고, 그건 미발견 판정의 전제라 매물 생명주기까지
# 영향을 준다. 로딩 시간 조금 줄이자고 건드릴 곳이 아니다.
#
# script도 넣지 않는다. 두 사이트 모두 카드를 JS로 그린다.
DEFAULT_BLOCKED_RESOURCES: frozenset[str] = frozenset({"image", "media", "font"})


@dataclass(slots=True)
class EngineConfig:
    headless: bool = True
    timeout_ms: int = 15_000
    viewport_width: int = 1280
    viewport_height: int = 800
    # None이면 실행 중인 Chromium 버전으로 만든다. 고정 문자열을 쓰고 싶으면 직접 준다.
    user_agent: str | None = None

    # 받지 않을 리소스 종류. 빈 집합을 주면 전부 받는다.
    #
    # 사이트별로 조정할 수 있게 열어 뒀다. 지연 로딩 방식에 따라서는 이미지 요청을
    # 끊으면 img의 src 속성이 영영 안 채워지는 경우가 있다 — 사이트가 로드 성공을
    # 확인한 뒤에 src를 넣는 구조라면 그렇다. 그런 사이트에서는 "image"를 빼면 된다.
    blocked_resources: frozenset[str] = DEFAULT_BLOCKED_RESOURCES


def build_user_agent(browser: Browser) -> str:
    """
    실행 중인 Chromium 버전으로 User-Agent를 만든다.

    browser.version 은 "120.0.6099.28" 같은 값을 준다. Playwright를 올리면
    UA도 함께 따라가므로 실제 브라우저와 어긋나지 않는다.
    """
    version = getattr(browser, "version", "") or ""

    if not version:
        return _DEFAULT_USER_AGENT

    return (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version} Safari/537.36"
    )


async def create_browser_context(
    playwright: Playwright,
    config: EngineConfig,
) -> tuple[Browser, BrowserContext]:
    browser = await playwright.chromium.launch(headless=config.headless)
    context = await browser.new_context(
        viewport={"width": config.viewport_width, "height": config.viewport_height},
        user_agent=config.user_agent or build_user_agent(browser),
    )

    if config.blocked_resources:
        await _block_resources(context, config.blocked_resources)

    return browser, context


async def _block_resources(context: BrowserContext, kinds: frozenset[str]) -> None:
    """
    지정한 종류의 리소스 요청을 중단시킨다.

    사이트에 부담을 덜 주는 방향이기도 하다 — 우리가 쓰지도 않을 썸네일 수십 장을
    라운드마다 내려받지 않게 된다.
    """

    async def _route(route) -> None:
        if route.request.resource_type in kinds:
            await route.abort()
            return

        await route.continue_()

    await context.route("**/*", _route)


async def wait_for_cards(page: Page, selector: str, *, timeout_ms: int) -> bool:
    """
    카드가 하나라도 그려질 때까지 기다린다. 나타났으면 True, 시간 안에 못 봤으면 False.

    **예외를 올리지 않는 것이 핵심이다.** 검색 결과가 정말 0건인 페이지에서도 이 함수는
    타임아웃에 걸리는데, 그것을 실패로 올리면 source_runner가 페이지 실패로 세고
    브랜드 전체 실패로 번진다. "결과 0건은 실패가 아니라 정상 성공"이라는 규칙이
    깨지는 셈이다(app/crawler/source_runner.py 참고).

    고정 sleep을 대신한다. 페이지가 0.3초에 준비돼도 2초를 기다리던 것을, 준비되는
    즉시 넘어가게 바꾼 것이다. 페이지 수만큼 곱해지는 시간이라 체감이 크다.
    """
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms, state="attached")
        return True
    except PlaywrightTimeoutError:
        logger.info(
            "카드 셀렉터가 %dms 안에 나타나지 않았습니다. 결과 0건이거나 "
            "셀렉터가 바뀐 것일 수 있습니다: %s",
            timeout_ms,
            selector,
        )
        return False


async def scroll_page(page: Page, *, count: int, pause_seconds: float) -> bool:
    """
    무한 스크롤 페이지를 내리고, **끝까지 도달했는지**를 반환한다.

    반환값이 중요한 이유는 매물 생명주기 관리 때문이다. 스크롤 횟수 제한에 걸려서 못 본
    매물을 "사라졌다"고 판단하면 멀쩡한 매물이 비활성 처리된다. 끝까지 내려간 경우에만
    "이 검색 결과에 없다 = 실제로 사라졌다"고 말할 수 있다.

    문서 높이가 더 이상 늘지 않으면 바닥으로 본다. count를 다 쓰고도 높이가 계속
    늘고 있으면 아직 더 남은 것이므로 False.
    """
    previous_height = await page.evaluate("document.body.scrollHeight")

    for _ in range(count):
        await page.mouse.wheel(0, 1000)
        await asyncio.sleep(pause_seconds)

        current_height = await page.evaluate("document.body.scrollHeight")

        if current_height == previous_height:
            # 높이가 그대로면 더 불러올 것이 없다. 다만 로딩이 늦을 수 있어
            # 한 번 더 기다렸다가 확인한다.
            await asyncio.sleep(pause_seconds)

            if await page.evaluate("document.body.scrollHeight") == current_height:
                return True

        previous_height = current_height

    return False


# (raw_text, detail_url, image_url) -> 파싱된 dict | None
ParseCardFn = Callable[[str, str, str | None], dict | None]
# href -> 상세 URL(유효하지 않으면 None). 사이트마다 절대/상대경로 규칙이 달라 콜백으로 받는다.
ResolveUrlFn = Callable[[str], str | None]


async def collect_cards(
    page: Page,
    *,
    link_selector: str,
    resolve_url: ResolveUrlFn,
    parse_card: ParseCardFn,
) -> tuple[dict[str, dict], ParseHealth]:
    """
    검색 결과 페이지에서 link_selector에 매칭되는 <a> 카드를 전부 훑어서
    (href 추출 -> 상세 URL 검증 -> 텍스트/이미지 추출 -> parse_card 콜백) 순서로 처리하고,
    상세 URL을 키로 중복 제거한 dict와 **파싱 성적**을 함께 반환한다.

    성적을 함께 돌려주는 이유:
        카드 하나가 실패해도 전체 수집을 막지 않는 판단은 맞다. 사이트에는 광고나
        형식이 다른 항목이 늘 섞여 있다. 문제는 그 실패가 **조용하다는** 것이다.
        DOM이 바뀌어 500개 중 480개를 못 읽어도 예외 없이 끝나고 건수만 줄어든다.

        더 위험한 건 그다음이다. 못 읽은 매물을 "이 범위에서 사라졌다"고 판단하면
        멀쩡한 매물이 대량으로 비활성 처리된다. 그래서 성적을 위로 전달해
        수집 완전성 판단에 반영한다(app/domain/parse_health.py 참고).

    세는 기준:
        seen       셀렉터에 걸린 카드 전부
        attempted  유효 URL과 비어 있지 않은 텍스트를 갖춰 파서에 넘긴 것
        parsed     파서가 결과를 돌려준 것

        "판매하기" 버튼처럼 매물이 아닌 링크는 attempted에서 빠진다. 이런 걸
        실패로 세면 실패율이 늘 높게 나와 진짜 문제를 못 알아본다.
    """
    cards = await page.query_selector_all(link_selector)
    results: dict[str, dict] = {}
    health = ParseHealth(seen=len(cards))

    for card in cards:
        try:
            href = await card.get_attribute("href")
            detail_url = resolve_url(href) if href else None

            if not detail_url:
                continue

            raw_text = await card.inner_text()

            if not raw_text.strip():
                continue

            img_elem = await card.query_selector("img")
            image_url = await img_elem.get_attribute("src") if img_elem else None

            # 여기서부터가 진짜 파싱이다. 위의 continue들은 애초에 매물이 아닌
            # 요소를 걸러낸 것이라 실패로 세지 않는다.
            health.attempted += 1

            parsed = parse_card(raw_text, detail_url, image_url)

            if parsed is None:
                # 파서가 유효하지 않은 카드로 판단했다. 규칙이 안 맞는 경우가
                # 여기 쌓이므로 실패로 센다.
                continue

            results[detail_url] = parsed
            health.parsed += 1
        except Exception as exc:
            # 카드 하나 파싱 실패는 전체 수집을 막지 않는다. 다만 디버그 로그를
            # 남겨 셀렉터가 바뀌었을 때 무엇이 터졌는지 추적할 수 있게 한다.
            logger.debug("카드 파싱 중 예외: %s: %s", type(exc).__name__, exc)
            continue

    if health.is_degraded:
        logger.warning(
            "카드 파싱 실패율이 높습니다: %d/%d (%.0f%%). "
            "사이트 DOM이 바뀌었을 수 있습니다.",
            health.failed,
            health.attempted,
            health.failure_rate * 100,
        )

    return results, health


def save_json(items, output_path: Path) -> None:
    """CrawledItem 리스트를 JSON으로 저장. 두 사이트 크롤러 CLI/스케줄러가 공용으로 쓴다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = [item.to_dict() for item in items]

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )