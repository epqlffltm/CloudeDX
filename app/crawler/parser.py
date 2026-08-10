#app/crawler/parser.py

"""
파서
"""

import re
from urllib.parse import urlparse

from typing import TYPE_CHECKING

from app.crawler.models import CrawledItem

if TYPE_CHECKING:
    from selenium.webdriver.remote.webelement import WebElement


_PRICE_PATTERN = re.compile(r"(?:\d[\d,]*\s*원|나눔)")
_TIME_PATTERN = re.compile(
    r"(?:방금\s*전|(?:끌올\s*)?\d+\s*(?:초|분|시간|일|주|개월|달|년)\s*전)"
)
_IGNORED_LINES = {
    "판매완료",
    "거래완료",
    "예약중",
    "끌올",
    "·",
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ·\t\r\n")


def parse_price_value(price: str | None) -> int | None:
    if not price:
        return None

    if "나눔" in price:
        return 0

    digits = re.sub(r"[^0-9]", "", price)
    return int(digits) if digits else None


def is_item_detail_url(url: str | None) -> bool:
    """
    검색 목록 자체가 아니라 실제 매물 상세 URL인지 확인한다.

    예:
    /kr/buy-sell/abc-xyz-123/  -> True
    /kr/buy-sell/              -> False
    """

    if not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    prefix = "/kr/buy-sell/"
    return path.startswith(prefix) and path != prefix.rstrip("/")


def _extract_lines(text: str) -> list[str]:
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = normalize_text(raw_line)

        if not line:
            continue

        # 판매완료가 제목 앞에 붙어서 들어오는 경우도 대비한다.
        if line.startswith("판매완료") and line != "판매완료":
            line = normalize_text(line.removeprefix("판매완료"))

        if line:
            lines.append(line)

    return lines


def _find_price(lines: list[str]) -> str | None:
    for line in lines:
        match = _PRICE_PATTERN.search(line)
        if match:
            return normalize_text(match.group(0))
    return None


def _find_time(text: str) -> str | None:
    match = _TIME_PATTERN.search(text)
    return normalize_text(match.group(0)) if match else None


def _find_title(lines: list[str], price: str | None) -> str | None:
    for line in lines:
        if line in _IGNORED_LINES:
            continue
        if price and price in line:
            continue
        if _TIME_PATTERN.search(line):
            continue
        if line.startswith(("관심 ", "채팅 ")):
            continue
        return line

    return None


def _find_region(
    lines: list[str],
    title: str | None,
    price: str | None,
    time_text: str | None,
) -> str | None:
    """
    제목/가격/시간/상태가 아닌 카드 텍스트를 지역 후보로 선택한다.

    기존 코드처럼 '첫 번째 애매한 줄'을 바로 지역으로 잡지 않기 때문에
    제목이 지역 필드에 중복되는 문제를 줄인다.
    """

    candidates: list[str] = []

    for line in lines:
        if line in _IGNORED_LINES:
            continue
        if title and line == title:
            continue
        if price and price in line:
            continue
        if time_text and time_text in line:
            continue
        if _TIME_PATTERN.search(line):
            continue
        if line.startswith(("관심 ", "채팅 ")):
            continue

        candidates.append(line)

    return candidates[0] if candidates else None


def parse_card_text(
    text: str,
    *,
    url: str,
    image_url: str | None = None,
) -> CrawledItem | None:
    """
    Selenium 요소 없이도 테스트할 수 있는 순수 파싱 함수.
    """

    lines = _extract_lines(text)

    if not lines:
        return None

    is_sold = "판매완료" in text or "거래완료" in text
    price = _find_price(lines)
    time_text = _find_time(text)
    title = _find_title(lines, price)

    if not title:
        return None

    region = _find_region(
        lines,
        title=title,
        price=price,
        time_text=time_text,
    )

    return CrawledItem(
        title=title,
        price=price,
        price_value=parse_price_value(price),
        region=region,
        time_text=time_text,
        image_url=image_url,
        url=url,
        is_sold=is_sold,
    )


def parse_anchor(anchor: "WebElement") -> CrawledItem | None:
    """
    당근 매물 <a> 요소 하나를 CrawledItem으로 변환한다.

    Selenium 관련 import는 이 함수 안에서만 수행한다.
    덕분에 순수 텍스트 파서 테스트는 Selenium 설치 없이도 실행 가능하다.
    """

    from selenium.common.exceptions import (
        NoSuchElementException,
        StaleElementReferenceException,
    )
    from selenium.webdriver.common.by import By

    try:
        url = anchor.get_attribute("href")

        if not is_item_detail_url(url):
            return None

        text = anchor.text.strip()
        if not text:
            return None

        image_url: str | None = None

        try:
            image = anchor.find_element(By.TAG_NAME, "img")
            image_url = (
                image.get_attribute("src")
                or image.get_attribute("data-src")
                or image.get_attribute("data-lazy-src")
            )
        except NoSuchElementException:
            pass

        return parse_card_text(
            text,
            url=url,
            image_url=image_url,
        )

    except StaleElementReferenceException:
        # 스크롤 중 DOM이 갱신된 경우 해당 요소 하나만 건너뛴다.
        return None
