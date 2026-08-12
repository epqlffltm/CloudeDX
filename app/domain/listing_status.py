# app/domain/listing_status.py

"""
매물 판매 상태 표기를 읽는 규칙.

두 사이트가 같은 한국어 표기를 쓰는데(판매완료·거래완료·예약중) 각자 파서에 흩어져
있으면 한쪽만 고치게 된다. 실제로 그런 상태였다 — 당근에는 판정이 있고 중고나라에는
없어서, 같은 상황의 매물이 사이트에 따라 다르게 취급됐다.

표기가 하는 일이 둘이라는 점이 중요하다.

1. **판매 여부 판정** — is_sold를 결정하고, 그 값이 매물 생명주기로 이어진다
   (app/db/repository.py 참고).
2. **제목 오염 방지** — 배지가 카드 텍스트의 별도 줄로 렌더링되는 경우가 있다.
   그 줄을 걸러내지 않으면 제목이 "판매완료"가 되어 버린다. 중고나라 파서에 실제로
   이 결함이 있었다.
"""

# 거래가 끝났다는 표기. 이게 보이면 더 이상 살 수 없는 매물이다.
SOLD_MARKERS: frozenset[str] = frozenset({"판매완료", "거래완료", "판매 완료", "거래 완료"})

# 아직 거래 중이지만 다른 사람이 예약한 상태. 살 수 없다는 점은 같지만 되돌아올 수
# 있어서 판매완료와 구분한다. 지금은 is_sold로 취급하지 않는다 — 예약이 취소되면
# 다시 판매중이 되는데, 그때 매물을 되살릴 경로가 upsert에 이미 있기 때문이다.
RESERVED_MARKERS: frozenset[str] = frozenset({"예약중", "예약 중"})

# 제목이 될 수 없는 줄. 배지·라벨류가 카드 텍스트에 섞여 들어온다.
NON_TITLE_LINES: frozenset[str] = (
    SOLD_MARKERS
    | RESERVED_MARKERS
    | frozenset({"인증셀러", "안전결제", "끌올", "무료배송", "배송비 별도", "·"})
)


def is_sold(text: str | None) -> bool:
    """
    카드 텍스트에 판매완료 표기가 있는지.

    부분 문자열로 찾는 이유는 배지가 다른 텍스트에 붙어 나오는 경우가 있어서다
    ("판매완료 샤넬 클래식 플랩"처럼 한 줄로 합쳐지기도 한다).
    """
    if not text:
        return False

    return any(marker in text for marker in SOLD_MARKERS)


def is_reserved(text: str | None) -> bool:
    """예약중 표기가 있는지. 현재 is_sold와는 별개로 다루며 저장하지는 않는다."""
    if not text:
        return False

    return any(marker in text for marker in RESERVED_MARKERS)


def strip_status_markers(line: str) -> str:
    """
    줄 앞에 붙은 상태 배지를 떼어낸다.

    "판매완료샤넬 클래식 플랩"처럼 배지와 제목이 한 줄로 합쳐져 들어오는 경우를
    처리한다. 배지만 있는 줄이면 빈 문자열이 되므로 호출부가 걸러내면 된다.
    """
    result = line.strip()

    for marker in SOLD_MARKERS | RESERVED_MARKERS:
        if result.startswith(marker):
            result = result.removeprefix(marker).strip()

    return result


def is_title_candidate(line: str) -> bool:
    """
    이 줄을 제목으로 삼아도 되는지.

    배지만 있는 줄을 제목으로 잡으면 "판매완료"라는 제목의 매물이 DB에 쌓인다.
    """
    stripped = line.strip()

    return bool(stripped) and stripped not in NON_TITLE_LINES