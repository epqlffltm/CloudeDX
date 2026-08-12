# app/domain/timeparse.py

"""
'3시간 전' 같은 상대 시각 표기를 실제 시각(datetime)으로 바꾼다.

두 사이트 모두 카드에 절대 날짜를 안 쓰고 "며칠 전" 형태로만 보여준다. 개별 매물
페이지에 들어가면 정확한 날짜가 있을 수 있지만, 그러려면 매물 수만큼 페이지를 더
방문해야 한다. 목록에서 이미 얻은 문자열을 변환하면 추가 요청 없이 등록 시각을
채울 수 있다.

정밀도의 한계는 표기 자체에서 온다. "3시간 전"은 ±30분, "2달 전"은 ±보름 수준이다.
그래서 화면에서도 분 단위로 단정하지 않고 상대 표기로 되돌려 보여준다.

'끌올'(끌어올림)은 판매자가 글을 상단으로 올린 시각이라 최초 등록일이 아니다.
당근은 이때 "끌올 2일 전"으로 표기하는데, 이 함수는 접두어를 떼고 시각만 읽는다.
즉 끌올한 매물의 등록 시각은 실제보다 최근으로 잡힌다 — 사이트가 원래 등록일을
노출하지 않으므로 목록 수집만으로는 구분할 방법이 없다.
"""

import re
from datetime import UTC, datetime, timedelta

# "끌올 2일 전", "방금 전", "3시간 전" 등에서 숫자와 단위를 뽑는다.
_RELATIVE_PATTERN = re.compile(
    r"(?:끌올\s*)?(\d+)\s*(초|분|시간|일|주|개월|달|년)\s*전"
)
_JUST_NOW_PATTERN = re.compile(r"방금\s*전")

# 각 단위를 초로 환산. 개월/년은 달력이 아니라 평균값 기준이다 — 어차피 원본 표기
# 자체가 대략적인 값이라, 달력 연산을 해도 정확해지지 않는다.
_UNIT_SECONDS = {
    "초": 1,
    "분": 60,
    "시간": 3600,
    "일": 86400,
    "주": 604800,
    "개월": 2592000,  # 30일
    "달": 2592000,
    "년": 31536000,  # 365일
}


def parse_relative_time(text: str | None, now: datetime | None = None) -> datetime | None:
    """
    상대 시각 문자열을 절대 시각으로 변환한다. 해석할 수 없으면 None.

    now를 넘기면 그 시점 기준으로 계산한다 (테스트용). 기본값은 현재 UTC 시각이다.

    >>> parse_relative_time("3시간 전", datetime(2026, 8, 11, 12, 0, tzinfo=UTC))
    datetime.datetime(2026, 8, 11, 9, 0, tzinfo=datetime.timezone.utc)
    """
    if not text:
        return None

    reference = now or datetime.now(UTC)

    if _JUST_NOW_PATTERN.search(text):
        return reference

    match = _RELATIVE_PATTERN.search(text)

    if match is None:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    return reference - timedelta(seconds=amount * _UNIT_SECONDS[unit])


def find_relative_time_text(text: str | None) -> str | None:
    """
    카드 원문에서 상대 시각 표기 부분만 잘라낸다.

    중고나라 파서는 제목/가격만 뽑고 시각은 건드리지 않았는데, 카드 원문에는 '3일 전'
    같은 표기가 함께 들어있는 경우가 있다. 없는 카드도 있어서 못 찾으면 None을 준다.
    """
    if not text:
        return None

    if _JUST_NOW_PATTERN.search(text):
        return "방금 전"

    match = _RELATIVE_PATTERN.search(text)

    return match.group(0).strip() if match else None