# app/domain/brands.py

"""
브랜드 어휘와 표기 판정.

수집 대상 브랜드(LUXURY_BRANDS)는 크롤러가 검색어를 만드는 데 쓰고, 별칭 사전은
제목에서 **실제 브랜드를 다시 판정하는 데** 쓴다. 둘을 나눈 이유는 검색어와 실제
상품이 자주 다르기 때문이다.

실측 데이터 599건에서 확인한 것:

    "루이비통 가방"으로 검색한 218건 중 31건 이상이 실제로는 구찌였다.

셀러가 검색 노출을 위해 제목 끝에 브랜드를 20개씩 나열하기 때문이다.

    구찌 스네이크 클러치백 정품A급(영수증O)구찌프라다루이비통디올고야드샤넬셀린느...

이걸 그대로 두면 "루이비통 최저가"에 구찌 가격이 섞인다. 브랜드가 틀리면 모델
그룹화도 처음부터 어긋나므로, 정규화 이전에 잡아야 하는 문제다.
"""

import re

# 수집 대상. 이 목록을 고치면 크롤러의 검색어와 화면의 필터 선택지가 함께 바뀐다.
LUXURY_BRANDS: tuple[str, ...] = ("구찌", "에르메스", "샤넬", "루이비통")

# 수집 대상 브랜드의 표기 변형.
# 실측에서 "루이뷔통"(뷔) 표기가 나왔다. 사이트가 아니라 셀러가 쓰는 말이라
# 오타와 변형이 계속 나온다고 보는 게 맞다.
TARGET_ALIASES: dict[str, tuple[str, ...]] = {
    "샤넬": ("샤넬", "chanel"),
    "구찌": ("구찌", "gucci", "구찌시마"),
    "루이비통": ("루이비통", "루이뷔통", "louisvuitton", "louis vuitton"),
    "에르메스": ("에르메스", "hermes"),
}

# 수집 대상은 아니지만 판정에 필요한 브랜드.
#
# 이 목록이 있어야 "구찌 제목인데 루이비통으로 저장된" 경우를 잡을 수 있고,
# 대상 외 브랜드 상품을 걸러낼 수 있다. 실측에서 걸러진 것들을 그대로 담았다.
OTHER_ALIASES: dict[str, tuple[str, ...]] = {
    "프라다": ("프라다", "prada"),
    "디올": ("디올", "dior"),
    "셀린느": ("셀린느", "셀린", "celine"),
    "보테가": ("보테가베네타", "보테가", "bottega"),
    "생로랑": ("생로랑", "ysl", "saintlaurent"),
    "발렌시아가": ("발렌시아가", "balenciaga"),
    "고야드": ("고야드", "goyard"),
    "버버리": ("버버리", "burberry"),
    "펜디": ("펜디", "fendi"),
    "미우미우": ("미우미우", "miumiu"),
    "마르지엘라": ("메종마르지엘라", "마르지엘라", "margiela"),
    "톰브라운": ("톰브라운", "thombrowne"),
    "베르사체": ("베르사체", "versace"),
    "르메르": ("르메르", "lemaire"),
    "바오바오": ("바오바오", "baobao"),
    "자크뮈스": ("자크뮈스", "jacquemus"),
    "불가리": ("불가리", "bvlgari"),
    "까르띠에": ("까르띠에", "cartier"),
    "토즈": ("토즈", "tods"),
    "질스튜어트": ("질스튜어트",),
    "더리움": ("더리움",),
}

ALL_ALIASES: dict[str, tuple[str, ...]] = {**TARGET_ALIASES, **OTHER_ALIASES}

# 스팸 꼬리 판정에 쓰는 표기. 대상/비대상을 가리지 않고 브랜드로 보이는 것은 전부 넣는다.
# 나열 자체가 신호라서, 어느 브랜드인지는 중요하지 않다.
_SPAM_TOKENS: tuple[str, ...] = tuple(
    {alias for aliases in ALL_ALIASES.values() for alias in aliases}
    | {
        "막스마라", "산드로", "마쥬", "마랑", "이자벨마랑", "메종키츠네", "한섬",
        "로저비비에", "마놀로블라닉", "테수토", "타임", "마인", "이세이미야케",
    }
)

# 스팸 꼬리로 판정할 조건.
#
# 실측 599건에서 제목당 브랜드 언급 수가 1개(80%)와 8개 이상(15%)으로 양분됐다.
# 중간이 거의 없어서 임계값을 잡기 쉬웠다.
_SPAM_MIN_HITS = 3  # 브랜드가 몇 개 몰리면 꼬리로 보는가
_SPAM_WINDOW = 30  # 그 몇 글자 안에 몰려야 하는가
_SPAM_MIN_OFFSET = 6  # 앞에서 최소 몇 자는 남기는가 (상품명 자체를 지우지 않기 위해)


def normalize(text: str) -> str:
    """
    비교용 정규화. 공백·하이픈·구분자를 없애고 소문자로 만든다.

    띄어쓰기 없는 표기가 흔해서 필요하다 — "구찌실비백", "구찌홀스빗1955탑핸들"처럼
    붙여 쓰는 제목이 실제로 많다. 토큰 분리로는 이런 것을 못 잡는다.
    """
    return re.sub(r"[\s\-_·,/.]", "", text.lower())


def strip_spam_tail(title: str) -> str:
    """
    브랜드명이 촘촘히 나열되는 꼬리를 잘라낸다.

    셀러가 검색 노출을 위해 붙이는 구간이라 상품 정보가 아니다. 그대로 두면
    브랜드 판정이 어긋나고, 모델명 추출도 방해받는다.

    앞에서부터 훑되 최소 _SPAM_MIN_OFFSET 자는 남긴다. 상품명 자체에 브랜드가
    들어가므로 위치 0부터 자르면 제목이 통째로 사라진다 — 처음 구현했을 때
    "구찌 홀스빗 크로스백..."이 빈 문자열이 되는 버그가 실제로 있었다.
    """
    positions = sorted(
        match.start()
        for token in _SPAM_TOKENS
        for match in re.finditer(re.escape(token), title)
        if match.start() >= _SPAM_MIN_OFFSET
    )

    if len(positions) < _SPAM_MIN_HITS:
        return title.strip(" ,./()")

    for i in range(len(positions) - _SPAM_MIN_HITS + 1):
        window = positions[i : i + _SPAM_MIN_HITS]

        if window[-1] - window[0] <= _SPAM_WINDOW:
            return title[: window[0]].strip(" ,./()")

    return title.strip(" ,./()")


def detect_brand(title: str) -> str | None:
    """
    제목에서 실제 브랜드를 판정한다. 알 수 없으면 None.

    **가장 앞에 나오는 브랜드가 진짜다.** 실측 92건의 스팸 제목을 확인한 결과
    이 규칙이 어긋난 경우가 없었다 — 상품명이 앞에 오고 검색용 나열이 뒤에 붙는다.

    스팸 꼬리를 먼저 잘라내고 판정하므로, 꼬리에만 등장하는 브랜드는 후보에서 빠진다.
    """
    clean = strip_spam_tail(title)
    normalized = normalize(clean)

    best_position = len(normalized) + 1
    best_brand = None

    for brand, aliases in ALL_ALIASES.items():
        for alias in aliases:
            position = normalized.find(normalize(alias))

            if 0 <= position < best_position:
                best_position = position
                best_brand = brand

    return best_brand


def detect_brand_with_model_hint(title: str) -> str | None:
    """
    브랜드 표기가 없을 때 모델명으로 역추정한다.

    셀러가 브랜드를 생략하고 모델명만 쓰는 경우가 있다 — "클래식 미듐 핑크 은장",
    "GG마몽 마틀라쎄 미디엄 체인숄더백". 검색 결과로 들어온 것이라 맥락상 브랜드가
    분명한데, 제목만 보면 알 수 없다.

    모델 사전을 쓰므로 순환 임포트를 피하려고 함수 안에서 임포트한다.
    """
    brand = detect_brand(title)

    if brand is not None:
        return brand

    from app.domain.product_type import BAG_MODELS, find_model

    for candidate in TARGET_ALIASES:
        if find_model(title, candidate):
            # 여러 브랜드에 같은 모델명이 있으면 판정하지 않는다.
            matches = [b for b in BAG_MODELS if find_model(title, b)]
            return candidate if len(matches) == 1 else None

    return None


def is_target_brand(brand: str | None) -> bool:
    """수집 대상 브랜드인지. None이거나 대상 외 브랜드면 False."""
    return brand in TARGET_ALIASES