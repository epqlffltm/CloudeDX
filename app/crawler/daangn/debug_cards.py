# app/crawler/daangn/debug_cards.py

"""
당근마켓 검색 결과 페이지에서 셀렉터가 실제로 뭘 잡는지 확인하기 위한 디버그 스크립트.
파싱/필터링을 거치지 않고, ITEM_LINK_SELECTOR에 매칭되는 <a> 요소들의 href와 원본
텍스트를 그대로 출력하고 페이지 스크린샷을 저장한다.

0건 문제처럼 "필터가 너무 세게 걸렀는지, 애초에 셀렉터가 실제 매물 카드를 못 잡는지"
구분할 때 쓴다.

사용: uv run python -m app.crawler.daangn.debug_cards --query "아이폰"
"""

import argparse
import asyncio
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.crawler.base import EngineConfig, create_browser_context, scroll_page
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import ITEM_LINK_SELECTOR
from app.crawler.daangn.parser import is_item_detail_url


def _resolve_url(href: str | None) -> str | None:
    if not href:
        return None
    return href if href.startswith("http") else f"https://www.daangn.com{href}"


async def _debug(query: str, scrolls: int) -> None:
    config = DaangnCrawlerConfig(query=query, headless=False, scroll_count=scrolls)
    engine_config = EngineConfig(headless=False, timeout_ms=config.timeout_ms)

    url = f"{config.base_url}?{urlencode({'search': config.query})}"

    async with async_playwright() as p:
        browser, context = await create_browser_context(p, engine_config)
        page = await context.new_page()
        page.set_default_timeout(config.timeout_ms)

        print(f"[debug] 접속: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=config.timeout_ms)

        await scroll_page(page, count=scrolls, pause_seconds=config.scroll_pause_seconds)

        screenshot_path = Path("data/daangn_debug.png")
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"[debug] 스크린샷 저장: {screenshot_path.resolve()}")
        print(f"[debug] 페이지 제목: {await page.title()}")

        cards = await page.query_selector_all(ITEM_LINK_SELECTOR)
        print(f"[debug] 셀렉터({ITEM_LINK_SELECTOR})에 매칭된 <a> 총 개수: {len(cards)}")

        accepted: list[tuple[str, str]] = []
        rejected_sample: list[str] = []

        for card in cards:
            href = await card.get_attribute("href")
            full_url = _resolve_url(href)

            if full_url and is_item_detail_url(full_url):
                raw_text = (await card.inner_text()).replace("\n", " | ")
                accepted.append((full_url, raw_text))
            elif len(rejected_sample) < 5:
                rejected_sample.append(href or "(href 없음)")

        print(f"[debug] is_item_detail_url 통과(매물 상세 후보): {len(accepted)}개")
        print(f"[debug] 거부된 예시 (앞 5개): {rejected_sample}")

        for i, (item_url, text) in enumerate(accepted[:15]):
            print(f"[accepted {i}] url={item_url}")
            print(f"     text={text[:200]}")

        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="당근마켓 카드 매칭 디버그")
    parser.add_argument("--query", default="아이폰")
    parser.add_argument("--scrolls", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(_debug(args.query, args.scrolls))


if __name__ == "__main__":
    main()