# app/crawler/daangn/parser.py

"""
당근마켓 상품 카드 텍스트 파싱.
Playwright 요소 없이도 테스트할 수 있는 순수 함수로 분리 (joongna/parser.py와 동일한 방침).
파싱 규칙 자체는 기존 Selenium 버전(app/crawler/parser.py)과 동일하다.
"""

import re
from urllib.parse import urlparse

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
    검색 목록/카테고리 페이지가 아니라 실제 매물 상세 URL인지 확인한다.

    예:
    /kr/buy-sell/abc-xyz-123/           -> True  (진짜 매물 상세)
    /kr/buy-sell/                        -> False (검색 홈)
    /kr/buy-sell/s/?search=자전거         -> False (관련 검색어/카테고리 칩. /s 경로는 검색 결과 페이지지 매물이 아니다)
    """
    if not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    prefix = "/kr/buy-sell/"
    if not path.startswith(prefix):
        return False

    remainder = path[len(prefix):]
    if not remainder:
        return False

    # '/kr/buy-sell/s' 이하는 검색결과/카테고리 경로다. 관련 검색어, 인기 카테고리
    # 바로가기 칩이 전부 이 경로를 쓰기 때문에 명시적으로 제외한다.
    if remainder == "s" or remainder.startswith("s/"):
        return False

    return True


def _extract_lines(text: str) -> list[str]:
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = normalize_text(raw_line)

        if not line:
            continue

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
    "첫 번째 애매한 줄"을 바로 지역으로 잡지 않기 때문에 제목이 지역 필드에
    중복되는 문제(dangun.py 시절 버그)를 반복하지 않는다.
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
) -> dict | None:
    """
    카드 텍스트를 파싱해서 dict로 반환. 실패하면 None.
    (예전에는 여기서 바로 CrawledItem을 만들었는데, joongna와 형태를 맞추기 위해
    dict만 반환하고 CrawledItem 조립은 crawler.py의 _to_item()이 담당한다.)
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

    if price is None and region is None and time_text is None:
        # 진짜 매물 카드라면 가격/지역/시간 중 최소 하나는 거의 항상 있다.
        # 셋 다 없으면 '인기 검색어'나 카테고리 바로가기 같은 비-매물 카드로 보고 버린다.
        return None

    return {
        "title": title,
        "price": price,
        "region": region,
        "time_text": time_text,
        "image_url": image_url,
        "url": url,
        "is_sold": is_sold,
    }