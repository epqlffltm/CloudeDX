# app/domain/collection.py

"""
수집 결과와 "어디까지 확실히 봤는가"를 함께 나르는 타입.

매물 생명주기 관리 때문에 필요해졌다. 크롤링 결과에 없는 매물을 "사라졌다"고 판단하려면
**그 범위를 빠짐없이 훑었다는 확신**이 있어야 한다. 확신이 없는데 판단하면 멀쩡한 매물이
비활성 처리된다.

확신을 잃는 경우는 넷이다.

1. **페이지 한계** — 중고나라를 브랜드당 3페이지만 긁는다. 매물이 늘어 4페이지로 밀린
   것은 사라진 게 아니라 우리 시야 밖으로 나간 것뿐이다. 정렬이 최신순이면 오래된
   매물부터 밀려나는데, 오래 안 팔린 매물이야말로 가격비교에서 가치가 크다.
2. **스크롤 한계** — 당근은 스크롤 횟수로 제한한다. 같은 문제.
3. **오류** — 페이지 하나가 실패했으면 그 페이지에 있던 매물을 못 본 것이다.
4. **파싱 실패** — 셀렉터는 카드를 찾았는데 내용을 못 읽은 경우다. 사이트가 DOM을
   바꾸면 예외 없이 조용히 일어난다. 이때 못 읽은 매물을 "사라졌다"고 판단하면
   DOM 변경 한 번에 멀쩡한 매물이 대량으로 비활성 처리된다.

그래서 크롤러는 "몇 건 가져왔다"만이 아니라 "이 범위를 다 봤다/못 봤다"를 같이 보고하고,
repository는 다 본 범위에 대해서만 미발견 판정을 한다.
"""

from dataclasses import dataclass, field

from app.domain.parse_health import ParseHealth


@dataclass(slots=True)
class Collection[T]:
    """
    한 번의 수집 결과.

    complete=False면 items에 없는 매물을 "사라졌다"고 해석하면 안 된다.
    """

    items: list[T] = field(default_factory=list)
    complete: bool = True

    # 이 수집에서 카드 파싱이 얼마나 성공했는지. 실패율이 높으면 complete를
    # 내려서 미발견 판정에서 제외한다.
    health: ParseHealth = field(default_factory=ParseHealth)

    def extend(self, other: "Collection[T]") -> None:
        """
        다른 수집 결과를 합친다. 완전성은 **둘 다 완전할 때만** 유지된다 —
        일부라도 놓쳤으면 합친 결과도 신뢰할 수 없다.
        """
        self.items.extend(other.items)
        self.complete = self.complete and other.complete
        self.health.merge(other.health)

    def apply_parse_health(self) -> None:
        """
        파싱 성적을 완전성 판단에 반영한다.

        실패율이 높으면 "이 범위를 빠짐없이 봤다"고 말할 수 없다. 못 읽은 매물이
        결과에 없을 뿐 사이트에는 그대로 있기 때문이다. 이걸 반영하지 않으면
        DOM 변경이 곧 대량 오탐으로 이어진다.
        """
        if self.health.is_degraded:
            self.complete = False


@dataclass(frozen=True, slots=True)
class SearchJob:
    """
    검색 한 번의 정의: 어느 브랜드를 어떤 서픽스로 검색해 어느 카테고리를 노리는가.

    크롤러는 이 단위로 돌고, 미발견 정리(CrawlScope)도 이 단위로 좁힌다.
    query가 실제 검색창에 들어가는 문자열이다.
    """

    brand: str
    category: str
    suffix: str

    @property
    def query(self) -> str:
        return f"{self.brand} {self.suffix}".strip()

    @property
    def label(self) -> str:
        """로그·헬스 리포트용 표기."""
        return f"{self.brand}·{self.category}"


@dataclass(frozen=True, slots=True)
class CrawlScope:
    """
    미발견 판정을 적용해도 되는 범위.

    (수집처, 브랜드) 단위다. 브랜드 하나가 실패해도 나머지 브랜드는 정상 판정할 수
    있어야 하므로 사이트 전체가 아니라 브랜드까지 쪼갠다.

    예: 당근마켓의 '샤넬'은 끝까지 봤고 '루이비통'은 0건이 의심스러우면,
        샤넬만 scope에 넣고 루이비통 매물은 건드리지 않는다.
    """

    source: str
    brands: frozenset[str]
    # 검색 잡의 카테고리. 기본 "bag"은 기존 호출처(가방만 수집하던 시절의
    # 테스트 포함)와의 호환용이다. 매물에 저장된 category는 분류 결과라
    # 검색 카테고리와 다를 수 있다 — 그 어긋남을 다루는 방식은 sweep_missing
    # 쪽 주석에 있다.
    category: str = "bag"

    def is_empty(self) -> bool:
        return not self.brands