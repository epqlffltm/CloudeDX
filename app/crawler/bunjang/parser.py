# app/crawler/bunjang/parser.py

"""
번개장터 검색 API 응답 항목을 우리 계약(dict)으로 바꾸는 순수 함수.
네트워크와 분리돼 있어 그대로 단위 테스트 표면이 된다.
"""


def parse_api_item(item: dict) -> dict | None:
    """
    API 항목 하나를 파싱한다. 필수 정보가 없으면 None — 호출부가 실패로 계상한다.

    - pid가 없으면 매물 URL을 만들 수 없으므로 버린다.
    - 가격이 0이거나 숫자가 아니면 "가격 미상"(None)으로 둔다. 번개장터의 0원은
      나눔·가격 미기재인데, 0을 그대로 저장하면 최저가 정렬 맨 앞이 오염된다 —
      당근의 '나눔'을 미상으로 접는 것과 같은 결정이다.
    """
    pid = item.get("pid")
    title = (item.get("name") or "").strip()

    if not pid or not title:
        return None

    try:
        price_value = int(float(item.get("price", 0)))
    except (TypeError, ValueError):
        price_value = 0

    image_url = (item.get("product_image") or "").strip() or None

    return {
        "title": title,
        "price_value": price_value if price_value > 0 else None,
        # 화면 표기용 문자열. 다른 소스는 사이트 원문을 보존하지만 번개장터
        # API는 숫자만 주므로, 화면 일관성을 위해 같은 형식으로 합성한다.
        "price": f"{price_value:,}원" if price_value > 0 else None,
        "image_url": image_url,
        "url": f"https://m.bunjang.co.kr/products/{pid}",
    }
