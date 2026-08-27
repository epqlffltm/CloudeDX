# app/domain/sellers.py

"""
입점 판매자 정보의 형식 규칙.

**검증만 한다. 진위는 확인하지 않는다.** 사업자등록번호가 실재하는지는 국세청
API(공공데이터포털)를 호출해야 알 수 있는데, 백엔드가 폐쇄망에 있어 나가지 못한다.
그래서 여기서 하는 일은 "형식이 맞는가"뿐이고, 화면에도 그렇게만 표시해야 한다 —
형식이 맞는다고 "인증된 사업자"라고 쓰면 하지 않은 검증을 했다고 말하는 셈이다.

시연 데이터는 형식은 맞되 누가 봐도 가짜인 값을 쓴다(123-45-67890 같은 연속 숫자).
형식까지 틀린 값을 쓰면 나중에 실제 검증을 붙일 때 전부 걸리므로, 형식은 지킨다.
"""

import re
from dataclasses import dataclass

# 사업자등록번호: 10자리, 3-2-5 구조.
#
# 흔한 오해가 두 가지 있다. "111-1111-1111"은 12자리라 형식 자체가 틀리고,
# "123-456-7890"은 10자리지만 3-3-4로 끊겨 역시 틀리다.
BUSINESS_NUMBER_PATTERN = re.compile(r"^\d{3}-\d{2}-\d{5}$")

# 전화번호: 지역번호(2~3자리) + 국번(3~4자리) + 번호(4자리).
# 02는 두 자리, 나머지 지역과 휴대폰은 세 자리다.
PHONE_PATTERN = re.compile(r"^0\d{1,2}-\d{3,4}-\d{4}$")

# 한국 영토의 대략적인 좌표 범위.
#
# 좌표는 브라우저에서 지오코딩해 폼으로 들어오거나 시드가 직접 넣는 값이라,
# 어느 쪽이든 서버가 받은 그대로 믿으면 안 된다. 범위를 벗어나면 지도에 핀이
# 엉뚱한 대륙에 찍힌다.
LAT_RANGE = (33.0, 39.0)
LNG_RANGE = (124.0, 132.0)


@dataclass(frozen=True, slots=True)
class SellerCheck:
    """형식 검사 결과. 하나라도 어긋나면 ok=False이고 reasons에 사유가 쌓인다."""

    ok: bool
    reasons: tuple[str, ...]


def normalize_business_number(raw: str) -> str:
    """
    사업자등록번호를 3-2-5 하이픈 형식으로 맞춘다.

    사람이 입력하는 값이라 하이픈을 빼거나 공백을 넣는 경우가 흔하다. 표기를
    통일하지 않으면 같은 사업자가 두 판매자로 저장된다.
    """
    digits = re.sub(r"\D", "", raw or "")

    if len(digits) != 10:
        return (raw or "").strip()

    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def is_valid_business_number(raw: str) -> bool:
    """형식만 본다. 국세청에 실재하는 번호인지는 확인하지 않는다."""
    return bool(BUSINESS_NUMBER_PATTERN.match(normalize_business_number(raw)))


def is_valid_phone(raw: str) -> bool:
    return bool(PHONE_PATTERN.match((raw or "").strip()))


def is_valid_coordinate(lat: float | None, lng: float | None) -> bool:
    """
    좌표가 한국 영토 범위 안인지 본다. 둘 다 None이면 "좌표 없음"이라 유효하다.

    한쪽만 있는 것은 유효하지 않다 — 위도만으로는 핀을 찍을 수 없고, 그 상태를
    허용하면 화면이 절반짜리 좌표를 어떻게 다룰지 매번 판단해야 한다.
    """
    if lat is None and lng is None:
        return True

    if lat is None or lng is None:
        return False

    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]


def check_seller(
    *,
    name: str,
    business_number: str,
    phone: str,
    has_store: bool,
    address: str | None,
    latitude: float | None,
    longitude: float | None,
) -> SellerCheck:
    """판매자 정보를 한 번에 검사한다."""
    reasons: list[str] = []

    if not (name or "").strip():
        reasons.append("판매자 이름이 비어 있습니다.")

    if not is_valid_business_number(business_number):
        reasons.append("사업자등록번호 형식이 올바르지 않습니다 (000-00-00000).")

    if not is_valid_phone(phone):
        reasons.append("전화번호 형식이 올바르지 않습니다 (00-000-0000).")

    # 매장이 있다고 했으면 주소가 있어야 한다. 매장이 없는 판매자는 주소가
    # 없는 것이 정상이고, 그 경우 화면은 지도를 아예 그리지 않는다.
    if has_store and not (address or "").strip():
        reasons.append("매장이 있는 판매자는 주소가 필요합니다.")

    if not is_valid_coordinate(latitude, longitude):
        reasons.append("좌표가 유효한 범위를 벗어났습니다.")

    return SellerCheck(ok=not reasons, reasons=tuple(reasons))


def mask_business_number(value: str) -> str:
    """
    사업자등록번호 뒤 5자리를 가린다. 목록처럼 넓게 노출되는 자리에 쓴다.

    사업자등록번호는 공개 정보이긴 하지만, 목록에 전체를 박아 두면 크롤링으로
    한 번에 수집된다. 상세 화면에서는 전체를 보여준다.
    """
    normalized = normalize_business_number(value)

    if not BUSINESS_NUMBER_PATTERN.match(normalized):
        return normalized

    return f"{normalized[:6]}*****"
