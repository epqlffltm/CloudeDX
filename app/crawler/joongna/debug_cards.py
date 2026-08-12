# app/crawler/joongna/debug_cards.py

"""
중고나라 검색 결과에서 카드가 실제로 어떤 텍스트를 내놓는지 확인하는 진단 도구.

당근에는 같은 도구가 있었는데 중고나라에는 없었다. 그 차이가 판매완료 판정이 한쪽에만
있던 이유 중 하나다 — 카드 원문을 볼 방법이 없으니 무엇을 찾아야 할지도 알 수 없었다.

파싱을 거치지 않은 원문을 그대로 보여주고, 파서가 그걸 어떻게 해석했는지 나란히 찍는다.
판매완료 표기가 실제로 어떤 모양으로 오는지(별도 줄인지, 제목에 붙는지, 아예 텍스트가
아니라 이미지 배지인지) 확인하는 것이 목적이다.

    uv run python -m app.crawler.joongna.debug_cards --brand "샤넬"
    uv run python -m app.crawler.joongna.debug_cards --brand "샤넬" --show-browser

텍스트에 판매완료 표기가 전혀 안 나온다면 배지가 이미지나 CSS로만 표현된다는 뜻이고,
그 경우 텍스트 파싱으로는 판정할 수 없다. 상세 페이지 확인(P1)으로 넘어가야 한다.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from app.crawler.base import EngineConfig, create_browser_context
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import ITEM_LINK_SELECTOR, JoongnaCrawler
from app.crawler.joongna.parser import parse_card_text
from app.domain.listing_status import RESERVED_MARKERS, SOLD_MARKERS

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.crawler.joongna.debug_cards",
        description="중고나라 카드 원문과 파싱 결과를 나란히 보여준다",
    )
    parser.add_argument("--brand", default="샤넬", help="검색할 브랜드")
    parser.add_argument("--page", type=int, default=1, help="확인할 페이지 번호")
    parser.add_argument("--limit", type=int, default=10, help="출력할 카드 수")
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="브라우저 창을 띄운다. 배지가 화면에 어떻게 보이는지 눈으로 확인할 때",
    )

    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    config = JoongnaCrawlerConfig(brand=args.brand)

    # URL 생성은 크롤러 것을 그대로 쓴다. 여기서 따로 만들면 두 곳이 갈라져
    # 진단 도구가 실제와 다른 페이지를 보여주게 된다.
    url = JoongnaCrawler(config)._build_url(args.page)

    async with async_playwright() as p:
        browser, context = await create_browser_context(
            p, EngineConfig(headless=not args.show_browser)
        )
        page = await context.new_page()

        try:
            print(f"[debug] 접속: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            screenshot = Path("data/joongna_debug.png")
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot), full_page=True)
            print(f"[debug] 스크린샷: {screenshot.resolve()}")

            cards = await page.query_selector_all(ITEM_LINK_SELECTOR)
            print(f"[debug] 셀렉터({ITEM_LINK_SELECTOR}) 매칭: {len(cards)}개\n")

            sold_seen = 0

            for index, card in enumerate(cards[: args.limit], start=1):
                text = await card.inner_text()
                href = await card.get_attribute("href") or ""
                parsed = parse_card_text(text, url=href)

                print(f"--- 카드 {index} ---")
                print("원문(줄 단위):")

                for line_no, line in enumerate(text.split("\n"), start=1):
                    stripped = line.strip()

                    if not stripped:
                        continue

                    # 상태 표기가 어느 줄에 있는지 눈에 띄게 표시한다.
                    mark = ""

                    if any(m in stripped for m in SOLD_MARKERS):
                        mark = "  <<< 판매완료 표기"
                        sold_seen += 1
                    elif any(m in stripped for m in RESERVED_MARKERS):
                        mark = "  <<< 예약중 표기"

                    print(f"  {line_no:2d}| {stripped}{mark}")

                if parsed:
                    print(
                        f"파싱 -> title={parsed['title']!r} "
                        f"price={parsed['price']!r} is_sold={parsed['is_sold']}"
                    )
                else:
                    print("파싱 -> None (유효하지 않은 카드로 판단)")

                print()

            if sold_seen == 0:
                print(
                    "[debug] 판매완료 표기가 텍스트에 하나도 없습니다.\n"
                    "        이 페이지에 판매완료 매물이 없거나, 배지가 이미지·CSS로만\n"
                    "        표현되어 텍스트 파싱으로는 판정할 수 없다는 뜻입니다.\n"
                    "        후자라면 --show-browser 로 화면을 확인하고, 상세 페이지\n"
                    "        확인 방식으로 넘어가야 합니다."
                )
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())