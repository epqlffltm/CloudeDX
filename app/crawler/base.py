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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.async_api import Browser, BrowserContext, Page, Playwright

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Selenium 버전 browser.py가 하던 navigator.webdriver 숨기기를 그대로 이식.
_HIDE_WEBDRIVER_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


@dataclass(slots=True)
class EngineConfig:
    headless: bool = True
    timeout_ms: int = 15_000
    viewport_width: int = 1280
    viewport_height: int = 800
    user_agent: str = _DEFAULT_USER_AGENT


async def create_browser_context(
    playwright: Playwright,
    config: EngineConfig,
) -> tuple[Browser, BrowserContext]:
    browser = await playwright.chromium.launch(headless=config.headless)
    context = await browser.new_context(
        viewport={"width": config.viewport_width, "height": config.viewport_height},
        user_agent=config.user_agent,
    )
    await context.add_init_script(_HIDE_WEBDRIVER_SCRIPT)
    return browser, context


async def scroll_page(page: Page, *, count: int, pause_seconds: float) -> None:
    for _ in range(count):
        await page.mouse.wheel(0, 1000)
        await asyncio.sleep(pause_seconds)


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
) -> dict[str, dict]:
    """
    검색 결과 페이지에서 link_selector에 매칭되는 <a> 카드를 전부 훑어서
    (href 추출 -> 상세 URL 검증 -> 텍스트/이미지 추출 -> parse_card 콜백) 순서로 처리하고,
    상세 URL을 키로 중복 제거한 dict를 반환한다.
    """
    cards = await page.query_selector_all(link_selector)
    results: dict[str, dict] = {}

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

            parsed = parse_card(raw_text, detail_url, image_url)
            if parsed is None:
                continue

            results[detail_url] = parsed
        except Exception:
            # 카드 하나 파싱 실패는 전체 수집을 막지 않는다.
            continue

    return results


def save_json(items, output_path: Path) -> None:
    """CrawledItem 리스트를 JSON으로 저장. 두 사이트 크롤러 CLI/스케줄러가 공용으로 쓴다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = [item.to_dict() for item in items]

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
