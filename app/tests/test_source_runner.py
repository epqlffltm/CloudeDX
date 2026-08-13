# app/tests/test_source_runner.py

"""
app.crawler.source_runner 테스트.

Playwright를 설치하지 않은 CI에서도 사이트 내부 수집 정책을 검증한다.
두 가지가 핵심이다.

1. **"정상적인 0건"과 "모든 시도가 예외로 실패"를 구분**한다. 결과 개수로 성공을
   판단하면 실제로 매물이 없는 상황을 장애로 오판한다.
2. **"이 범위를 빠짐없이 봤는가"를 정확히 보고**한다. 이 값이 틀리면 멀쩡한 매물이
   비활성 처리되거나(과신), 사라진 매물이 영원히 남는다(과소).
"""

import pytest

from app.crawler.source_runner import (
    AllBrandsFailedError,
    AllPagesFailedError,
    collect_brands,
    collect_pages,
)
from app.domain.collection import Collection

# ---------------------------------------------------------------------------
# collect_brands
# ---------------------------------------------------------------------------


async def test_sums_successful_results():
    async def crawl_brand(brand: str) -> Collection[str]:
        return Collection(items=[f"{brand}-1", f"{brand}-2"])

    collected, complete, health = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert collected.items == ["구찌-1", "구찌-2", "샤넬-1", "샤넬-2"]
    assert complete == {"구찌", "샤넬"}
    assert collected.complete is True


async def test_partial_failure_still_succeeds():
    async def crawl_brand(brand: str) -> Collection[str]:
        if brand == "구찌":
            raise RuntimeError("timeout")
        return Collection(items=[brand])

    collected, complete, health = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert collected.items == ["샤넬"]
    # 실패한 브랜드는 "다 봤다"고 말할 수 없다. 그 매물을 사라졌다고 판단하면 안 된다.
    assert complete == {"샤넬"}
    assert collected.complete is False


async def test_zero_items_is_success_but_not_verified():
    """
    이게 가장 미묘한 경계다.

    요청/파싱이 정상 종료되어 0건이 나온 것은 실패가 아니다. 하지만 **다 봤다고
    단정해서도 안 된다.** 봇 감지로 빈 페이지를 받으면 예외 없이 0건으로 끝난다.
    실제 로그에서 "당근마켓 '루이비통' 0건"이 나온 적이 있는데 나머지 브랜드는
    60건씩이었다. 이걸 믿고 미발견 처리하면 해당 브랜드 매물이 전량 사라진다.
    """

    async def crawl_brand(brand: str) -> Collection[str]:
        return Collection(items=[], complete=True)

    collected, complete, health = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert collected.items == []
    assert complete == set(), "0건 브랜드는 미발견 판정에서 빠져야 한다"


async def test_incomplete_brand_is_excluded():
    """수집 범위 한계에 걸린 브랜드는 결과에 포함하되 판정 대상에서는 뺀다."""

    async def crawl_brand(brand: str) -> Collection[str]:
        return Collection(items=[brand], complete=(brand == "샤넬"))

    collected, complete, health = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert set(collected.items) == {"구찌", "샤넬"}
    assert complete == {"샤넬"}


async def test_all_brands_failing_raises():
    async def crawl_brand(brand: str) -> Collection[str]:
        raise RuntimeError("차단")

    with pytest.raises(AllBrandsFailedError):
        await collect_brands(
            source_name="테스트",
            brands=("구찌", "샤넬"),
            crawl_brand=crawl_brand,
        )


async def test_empty_brand_list_rejected():
    async def crawl_brand(brand: str) -> Collection[str]:
        return Collection()

    with pytest.raises(ValueError):
        await collect_brands(source_name="테스트", brands=(), crawl_brand=crawl_brand)


# ---------------------------------------------------------------------------
# collect_pages
# ---------------------------------------------------------------------------


async def test_collects_multiple_pages():
    async def collect_page(page_num: int) -> list[str]:
        return [f"p{page_num}-a", f"p{page_num}-b"] if page_num <= 2 else []

    result = await collect_pages(
        source_name="테스트", max_pages=5, collect_page=collect_page
    )

    assert result.items == ["p1-a", "p1-b", "p2-a", "p2-b"]
    # 빈 페이지를 만나 멈췄으니 그 뒤로는 없다 = 끝까지 봤다.
    assert result.complete is True


async def test_hitting_page_limit_is_incomplete():
    """
    max_pages를 다 쓰고도 매물이 계속 나왔다면 아직 남아 있다는 뜻이다.
    이걸 완전하다고 보면, 페이지 밖으로 밀린 매물이 비활성 처리된다.
    중고나라를 브랜드당 3페이지만 긁기 때문에 실제로 자주 생기는 상황이다.
    """

    async def collect_page(page_num: int) -> list[str]:
        return [f"p{page_num}"]

    result = await collect_pages(
        source_name="테스트", max_pages=3, collect_page=collect_page
    )

    assert result.items == ["p1", "p2", "p3"]
    assert result.complete is False


async def test_page_error_makes_it_incomplete():
    """페이지 하나가 실패했으면 그 페이지의 매물을 못 본 것이다."""

    async def collect_page(page_num: int) -> list[str]:
        if page_num == 2:
            raise RuntimeError("timeout")
        return [f"p{page_num}"] if page_num == 1 else []

    result = await collect_pages(
        source_name="테스트", max_pages=3, collect_page=collect_page
    )

    assert result.items == ["p1"]
    assert result.complete is False


async def test_first_page_empty_is_complete():
    """정말로 검색 결과가 없는 경우. 0건이지만 끝까지 본 것은 맞다."""

    async def collect_page(page_num: int) -> list[str]:
        return []

    result = await collect_pages(
        source_name="테스트", max_pages=3, collect_page=collect_page
    )

    assert result.items == []
    assert result.complete is True


async def test_all_pages_failing_raises():
    async def collect_page(page_num: int) -> list[str]:
        raise RuntimeError("차단")

    with pytest.raises(AllPagesFailedError):
        await collect_pages(source_name="테스트", max_pages=3, collect_page=collect_page)


async def test_max_pages_must_be_positive():
    async def collect_page(page_num: int) -> list[str]:
        return []

    with pytest.raises(ValueError):
        await collect_pages(source_name="테스트", max_pages=0, collect_page=collect_page)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def test_extend_loses_completeness_if_either_side_is_incomplete():
    """일부라도 놓쳤으면 합친 결과도 신뢰할 수 없다."""
    a = Collection(items=[1], complete=True)
    a.extend(Collection(items=[2], complete=False))

    assert a.items == [1, 2]
    assert a.complete is False