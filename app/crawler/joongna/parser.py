# app/crawler/joongna/parser.py

"""
중고나라 상품 카드 텍스트 파싱.
daangn/parser.py와 동일한 방침 — Playwright 요소 없이도 순수 함수로 테스트 가능하게 분리.
파싱 규칙 자체는 팀 동료가 만든 jungonara_crawler.py의 로직을 그대로 옮겼다.
"""

import re

from app.domain.listing_status import (
    is_sold,
    is_title_candidate,
    strip_status_markers,
)
from app.domain.timeparse import find_relative_time_text


def parse_price_value(price: str | None) -> int | None:
    """'350,000원' 같은 문자열에서 숫자만 뽑아 int로 변환. 실패하면 None."""
    if not price:
        return None
    digits = re.sub(r"[^0-9]", "", price)
    return int(digits) if digits else None



# 가격으로 인정할 최소 금액. 중고나라 카드에는 찜 개수·조회수가 숫자만 있는 줄로
# 섞여 들어온다("1", "51" 같은 값). 세 자리면 가격으로 보던 예전 규칙에서는
# 찜 100개가 "100원"이 되어 최저가를 오염시켰다.
#
# 명품 가방 카테고리라 만 원 미만 매물은 사실상 없다. 실제로 있다 해도 놓치는 쪽이
# 찜 개수를 가격으로 읽는 것보다 낫다 — 후자는 시세를 통째로 무너뜨린다.
_MIN_PRICE = 10_000


def _read_price(line: str, lines: list[str], index: int) -> str | None:
    """
    한 줄을 가격으로 읽는다. 가격이 아니면 None.

    중고나라는 금액과 단위를 별도 줄로 렌더링한다.

        2| 250,000
        3| 원

    그래서 "250,000"만 저장하면 화면에 단위 없이 나온다. 다음 줄이 "원"이면 붙여서
    "250,000원"으로 만든다 — 사이트마다 표기가 제각각인 원문을 그대로 보존하되,
    적어도 무엇을 뜻하는지는 알아볼 수 있게 한다.
    """
    stripped = line.strip()

    # 단위만 있는 줄. 앞줄의 금액에 이미 붙였거나 금액이 걸러진 경우라 무시한다.
    # 이걸 가격으로 읽으면 price="원"이라는 값이 저장된다.
    if stripped == "원":
        return None

    if "원" in stripped:
        return line

    digits = stripped.replace(",", "")

    if not digits.isdigit():
        return None

    if int(digits) < _MIN_PRICE:
        return None

    # 다음 줄이 단위면 합친다.
    if index + 1 < len(lines) and lines[index + 1].strip() == "원":
        return f"{line}원"

    return line


def parse_card_text(
    raw_text: str,
    *,
    url: str,
    image_url: str | None = None,
) -> dict | None:
    """
    중고나라 상품 카드의 inner_text()를 파싱해서 dict로 반환. 실패하면 None.

    규칙:
    - 배지·라벨 줄(판매완료, 인증셀러 등)은 제목 후보에서 제외한다.
    - 처음 나오는 의미 있는 줄을 제목으로 삼는다.
    - 제목 다음으로 '원'이 포함되거나 숫자만 3자리 이상인 줄을 가격으로 삼는다.
    - 제목이 없거나 '판매하기'면 유효하지 않은 카드로 취급한다.

    카드 원문 전체에서 '3일 전' 같은 등록 시각 표기를 찾는다. 줄 단위가 아니라 원문
    전체를 훑는 이유는 이 표기가 어느 줄에 붙어 나올지 카드마다 다르기 때문이다.
    없는 카드도 있어서 못 찾으면 None으로 둔다.

    판매완료 판정도 같은 방식으로 원문 전체에서 찾는다. 예전에는 이 판정이 아예 없어서
    중고나라 매물은 팔려도 is_sold=False로 남았고, 연속 미발견 3회를 기다린 뒤에야
    목록에서 내려갔다. 당근은 판정이 있었으므로 같은 상황의 매물이 사이트에 따라 다르게
    취급되던 셈이다.

    **배지 줄을 제외하는 것이 판정만큼 중요하다.** 중고나라가 판매완료 배지를 카드
    텍스트의 별도 줄로 렌더링하면, 그 줄을 거르지 않을 경우 제목이 "판매완료"가 된다.
    실제로 이 파서에 그 결함이 있었다.

    참고: 원본 스크립트의 배송비(free_shipping) 정보는 공통 CrawledItem 모델에
    대응 필드가 없어서 여기서는 버려진다. 필요해지면 CrawledItem에 필드를 추가하면 된다.
    """
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if not lines:
        return None

    title = ""
    price = ""
    found_title = False

    for index, line in enumerate(lines):
        if not found_title:
            # 배지가 제목과 한 줄로 합쳐져 오는 경우가 있어 먼저 떼어낸다.
            candidate = strip_status_markers(line)

            if is_title_candidate(candidate) and len(candidate) > 1:
                title = candidate
                found_title = True

            continue

        if not price:
            price = _read_price(line, lines, index)

            if price:
                break

    if not title or title == "판매하기":
        return None

    return {
        "title": title,
        "price": price or None,
        "time_text": find_relative_time_text(raw_text),
        "is_sold": is_sold(raw_text),
        "url": url,
        "image_url": image_url,
    }