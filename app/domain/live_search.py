# app/domain/live_search.py

"""
검색어를 실시간 수집 잡으로 바꾸는 규칙.

사용자가 검색창에 친 문자열은 자유 텍스트다. 번개장터 API에 그대로 넘겨도 결과는
나오지만, 그러면 같은 뜻의 검색어가 서로 다른 잡으로 취급되어 락과 캐시가 무력해진다.
"샤넬 클래식", "샤넬클래식", "  샤넬 클래식 "이 각각 API를 한 번씩 치게 된다.

그래서 검색어를 정규형으로 접는다. 접는 규칙은 새로 만들지 않고 이미 있는 것을 쓴다 —
brands.normalize(공백·기호 제거), brands.detect_brand(별칭 판정),
product_type.classify_category(카테고리 판정). 크롤링 경로와 같은 어휘를 쓰지 않으면
"실시간으로 가져온 샤넬"과 "크롤링한 샤넬"의 표기가 갈라진다.

**이 모듈은 HTTP도 DB도 모른다.** 문자열을 받아 잡 정의를 돌려주는 순수 함수뿐이라
네트워크 없이 테스트할 수 있다. 크롤러 계층에서 Playwright를 걷어낸 것과 같은 방침이다.
"""

from dataclasses import dataclass

from app.domain.brands import detect_brand, normalize
from app.domain.product_type import classify_category

# 카테고리를 판정하지 못했을 때 검색어에 붙일 서픽스.
#
# 아무것도 안 붙이면 "샤넬"만으로 검색하게 되는데, 그러면 향수·키링·쇼핑백이 대량으로
# 딸려 온다. 실측 599건에서 24%가 비대상 품목이었던 그 문제다. 정제 단계가 걸러내긴
# 하지만, 애초에 덜 섞이게 하는 편이 API 호출 한 번의 수확을 높인다.
#
# 크롤러의 keyword_suffix 기본값과 같은 값이다(daangn/joongna config).
DEFAULT_SUFFIX = "가방"

# 위 서픽스가 뜻하는 카테고리. lock_key를 만들 때 쓴다 — 서픽스 문자열("가방")과
# 카테고리 키("bag")를 섞어 쓰면 "샤넬"과 "샤넬 가방"이 다른 키가 된다.
DEFAULT_CATEGORY = "bag"

# 실시간 조회를 걸 최소 길이. 한 글자로는 의미 있는 검색이 되지 않고 API만 두드린다.
MIN_QUERY_LENGTH = 2


@dataclass(frozen=True, slots=True)
class LiveQuery:
    """
    실시간 수집 한 번의 정의.

    lock_key는 중복 요청 방지와 캐시의 기준이다. 표기가 달라도 같은 뜻이면 같은 키가
    나와야 "샤넬클래식"과 "샤넬 클래식"이 API를 두 번 치지 않는다.
    """

    raw: str
    brand: str | None
    category: str | None
    keyword: str

    @property
    def lock_key(self) -> str:
        """
        락과 캐시의 기준 키.

        브랜드를 판정했으면 **원문이 아니라 정규 브랜드명**으로 만든다. 그래야
        "루이뷔통 가방"과 "루이비통 가방"이 같은 키가 된다 — 원문을 그대로 접으면
        별칭마다 API를 따로 치게 되어 락의 의미가 없어진다.

        API에 보내는 keyword는 원문을 유지한다. 별칭으로 검색해도 결과가 나오고,
        사용자가 친 표기가 그 사이트에서 더 잘 걸리는 경우도 있기 때문이다.
        접는 것은 "중복 요청인가"를 따지는 이 키뿐이다.
        """
        if self.brand:
            tail = self.category or DEFAULT_CATEGORY
            return normalize(f"{self.brand}{tail}")

        return normalize(self.keyword)


def build_live_query(raw: str) -> LiveQuery | None:
    """
    검색어를 실시간 수집 잡으로 바꾼다. 실시간 조회를 걸 값이 못 되면 None.

    None을 돌려주는 경우는 둘뿐이다 — 너무 짧거나, 정규화하면 빈 문자열이 되는 경우
    (공백·기호만 입력). 라우터는 None을 오류가 아니라 "실시간 조회 없이 DB 결과만
    준다"로 다룬다.

    **브랜드를 판정하지 못해도 None이 아니다.** 우리가 모르는 브랜드를 찾는 사람도
    결과를 봐야 한다. 대신 그 결과가 목록에 뜰지는 저장 단계의 정제 규칙이 정한다 —
    여기서 미리 거르면 판정 규칙이 두 곳으로 갈라진다.
    """
    text = (raw or "").strip()

    if len(text) < MIN_QUERY_LENGTH or not normalize(text):
        return None

    brand = detect_brand(text)
    category, _matched = classify_category(text, brand)

    # 검색어가 이미 카테고리를 특정하고 있으면 서픽스를 덧붙이지 않는다.
    # "샤넬 시계"에 "가방"을 붙이면 서로 배타적인 두 단어가 한 질의에 들어간다.
    # "샤넬 클래식"처럼 모델명으로 카테고리가 잡히는 경우도 마찬가지다.
    keyword = text if category else f"{text} {DEFAULT_SUFFIX}"

    return LiveQuery(raw=text, brand=brand, category=category, keyword=keyword)
