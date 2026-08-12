# app/domain/cleaning.py

"""
수집한 매물을 저장하기 전에 정제한다.

크롤러가 긁어온 그대로는 시세 계산에 쓸 수 없다. 실측 599건에서 **약 30%가
쓸 수 없는 데이터**였다.

| 문제 | 비율 |
|---|---|
| 가방이 아님 (향수·신발·쇼핑백·지갑) | 16% |
| 대상 외 브랜드 | 9% |
| 브랜드 판정 불가 | 4% |

특히 심각했던 것은 **브랜드 오분류**다. "루이비통 가방"으로 검색한 218건 중 31건
이상이 실제로는 구찌였다. 셀러가 검색 노출을 위해 제목 끝에 브랜드를 20개씩 나열하기
때문이다. 이걸 두면 "루이비통 최저가"에 구찌 가격이 섞인다.

정제는 **버리지 않고 표시한다.** 판정이 틀릴 수 있고, 규칙을 고쳤을 때 다시 판정하려면
원본이 남아 있어야 한다. 조회 기본값에서 제외하되 데이터는 보존하는 방식이다 —
매물 생명주기에서 is_active를 다루는 것과 같은 방침이다.
"""

from dataclasses import dataclass

from app.domain.brands import (
    detect_brand_with_model_hint,
    is_target_brand,
    strip_spam_tail,
)
from app.domain.product_type import find_model, is_bag


@dataclass(frozen=True, slots=True)
class CleanedTitle:
    """
    제목 정제 결과.

    원본(raw_title)을 함께 들고 다니는 이유는 판정 근거를 나중에 확인해야 하기
    때문이다. 규칙을 고치고 재판정할 때도 필요하다.
    """

    raw_title: str
    clean_title: str
    brand: str | None
    model: str | None
    is_usable: bool
    reject_reason: str | None

    @property
    def display_title(self) -> str:
        """화면에 보여줄 제목. 스팸 꼬리를 뗀 쪽이 읽기 좋다."""
        return self.clean_title or self.raw_title


def clean_title(title: str, *, search_brand: str | None = None) -> CleanedTitle:
    """
    제목을 정제하고 사용 가능 여부를 판정한다.

    search_brand는 크롤러가 어떤 검색어로 이 매물을 찾았는지다. 판정에는 쓰지
    않고 기록만 한다 — 검색어와 실제 상품이 다른 것이 바로 이 함수가 해결하려는
    문제이므로, 검색어를 믿으면 안 된다.
    """
    clean = strip_spam_tail(title)

    if not clean:
        return CleanedTitle(title, "", None, None, False, "제목이 비어 있음")

    brand = detect_brand_with_model_hint(clean)

    if brand is None:
        return CleanedTitle(title, clean, None, None, False, "브랜드 판정 불가")

    if not is_target_brand(brand):
        return CleanedTitle(title, clean, brand, None, False, f"대상 외 브랜드: {brand}")

    usable, reason = is_bag(clean, brand)

    if not usable:
        return CleanedTitle(title, clean, brand, None, False, f"가방 아님: {reason}")

    return CleanedTitle(title, clean, brand, find_model(clean, brand), True, None)