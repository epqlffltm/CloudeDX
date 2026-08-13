# app/domain/seller.py

"""
판매자 유형 판정.

중고나라는 일부 매물에 "인증셀러" 배지를 붙인다. 사이트가 검증한 사업자라는 뜻이고,
개인 거래보다 신뢰도가 높다는 신호다. 파서가 이 줄을 제목 후보에서 제외하기만 하고
값은 버리고 있었는데, 화면에 쓸 수 있는 정보라 살려 둔다.

**당근마켓에는 대응하는 배지가 없다.** 그래서 판정 결과를 세 갈래로 둔다.

    CERTIFIED   사이트가 인증한 셀러
    INDIVIDUAL  배지가 없는 개인 판매자
    None        판정할 수 없음 (당근마켓 전체)

None을 두는 것이 핵심이다. 당근 매물을 전부 INDIVIDUAL로 적으면 "당근은 개인거래만"
이라는 잘못된 사실이 데이터에 박힌다. 실제로는 우리가 모르는 것뿐이다.

이 구분은 사이트별로 같은 값의 의미가 달라지는 문제를 피하기 위한 것이고,
매물 생명주기에서 sold(사실)와 missing(추정)을 나눈 것과 같은 방침이다.
"""

from enum import StrEnum


class SellerType(StrEnum):
    """판매자 유형."""

    CERTIFIED = "certified"
    INDIVIDUAL = "individual"


# 사이트가 인증한 셀러임을 나타내는 배지 표기.
CERTIFIED_MARKERS: frozenset[str] = frozenset({"인증셀러", "인증 셀러", "공식판매자"})


def detect_seller_type(card_text: str | None) -> SellerType | None:
    """
    카드 텍스트에서 판매자 유형을 판정한다. 판정할 수 없으면 None.

    **배지 체계가 있는 사이트에서만 쓴다.** 배지가 없는 사이트(당근마켓)에서
    호출하면 모든 매물이 INDIVIDUAL이 되는데, 그건 "개인 판매자"가 아니라
    "우리가 모른다"는 뜻이라 사실과 다르다.
    """
    if card_text is None:
        return None

    if any(marker in card_text for marker in CERTIFIED_MARKERS):
        return SellerType.CERTIFIED

    return SellerType.INDIVIDUAL