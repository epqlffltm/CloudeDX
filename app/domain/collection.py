# app/domain/collection.py

"""
수집 결과와 "어디까지 확실히 봤는가"를 함께 나르는 타입.

매물 생명주기 관리 때문에 필요해졌다. 크롤링 결과에 없는 매물을 "사라졌다"고 판단하려면
**그 범위를 빠짐없이 훑었다는 확신**이 있어야 한다. 확신이 없는데 판단하면 멀쩡한 매물이
비활성 처리된다.

확신을 잃는 경우는 셋이다.

1. **페이지 한계** — 중고나라를 브랜드당 3페이지만 긁는다. 매물이 늘어 4페이지로 밀린
   것은 사라진 게 아니라 우리 시야 밖으로 나간 것뿐이다. 정렬이 최신순이면 오래된
   매물부터 밀려나는데, 오래 안 팔린 매물이야말로 가격비교에서 가치가 크다.
2. **스크롤 한계** — 당근은 스크롤 횟수로 제한한다. 같은 문제.
3. **오류** — 페이지 하나가 실패했으면 그 페이지에 있던 매물을 못 본 것이다.

그래서 크롤러는 "몇 건 가져왔다"만이 아니라 "이 범위를 다 봤다/못 봤다"를 같이 보고하고,
repository는 다 본 범위에 대해서만 미발견 판정을 한다.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Collection[T]:
    """
    한 번의 수집 결과.

    complete=False면 items에 없는 매물을 "사라졌다"고 해석하면 안 된다.
    """

    items: list[T] = field(default_factory=list)
    complete: bool = True

    def extend(self, other: "Collection[T]") -> None:
        """
        다른 수집 결과를 합친다. 완전성은 **둘 다 완전할 때만** 유지된다 —
        일부라도 놓쳤으면 합친 결과도 신뢰할 수 없다.
        """
        self.items.extend(other.items)
        self.complete = self.complete and other.complete


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

    def is_empty(self) -> bool:
        return not self.brands