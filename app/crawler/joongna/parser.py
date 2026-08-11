# app/crawler/joongna/parser.py

"""
중고나라 상품 카드 텍스트 파싱.
daangn/parser.py와 동일한 방침 — Playwright 요소 없이도 순수 함수로 테스트 가능하게 분리.
파싱 규칙 자체는 팀 동료가 만든 jungonara_crawler.py의 로직을 그대로 옮겼다.
"""

import re

from app.crawler.timeparse import find_relative_time_text


def parse_price_value(price: str | None) -> int | None:
    """'350,000원' 같은 문자열에서 숫자만 뽑아 int로 변환. 실패하면 None."""
    if not price:
        return None
    digits = re.sub(r"[^0-9]", "", price)
    return int(digits) if digits else None


def parse_card_text(
    raw_text: str,
    *,
    url: str,
    image_url: str | None = None,
) -> dict | None:
    """
    중고나라 상품 카드의 inner_text()를 파싱해서 dict로 반환. 실패하면 None.

    원본 스크립트 규칙 그대로:
    - '인증셀러' 줄은 건너뛴다.
    - 처음 나오는 의미 있는 줄(길이 2 이상)을 제목으로 삼는다.
    - 제목 다음으로 '원'이 포함되거나 숫자만 3자리 이상인 줄을 가격으로 삼는다.
    - 제목이 없거나 '판매하기'면 유효하지 않은 카드로 취급한다.

    여기에 더해 카드 원문 전체에서 '3일 전' 같은 등록 시각 표기를 찾는다. 줄 단위가
    아니라 원문 전체를 훑는 이유는 이 표기가 어느 줄에 붙어 나올지 카드마다 다르기
    때문이다. 없는 카드도 있어서 못 찾으면 None으로 둔다.

    참고: 원본 스크립트의 배송비(free_shipping) 정보는 공통 CrawledItem 모델에
    대응 필드가 없어서 여기서는 버려진다. 필요해지면 CrawledItem에 필드를 추가하면 된다.
    """
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if not lines:
        return None

    title = ""
    price = ""
    found_title = False

    for line in lines:
        if line == "인증셀러":
            continue

        if not found_title and len(line) > 1:
            title = line
            found_title = True
            continue

        if found_title and not price:
            stripped = line.replace(",", "")
            if "원" in line or (stripped.isdigit() and len(stripped) >= 3):
                price = line
                break

    if not title or title == "판매하기":
        return None

    return {
        "title": title,
        "price": price or None,
        "time_text": find_relative_time_text(raw_text),
        "url": url,
        "image_url": image_url,
    }
