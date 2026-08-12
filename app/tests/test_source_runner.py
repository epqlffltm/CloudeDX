# app/tests/test_source_runner.py

"""
app.crawler.source_runner 테스트.

Playwright를 설치하지 않은 CI에서도 사이트 내부 실패 정책을 검증한다.
특히 "정상적인 0건"과 "모든 시도가 예외로 실패"를 구분하는 것이 핵심이다.
"""

import pytest

from app.crawler.source_runner import (
    AllBrandsFailedError,
    AllPagesFailedError,
    collect_brands,
    collect_pages,
)


async def test_collect_brands_sums_successful_results():
    async def crawl_brand(brand: str) -> list[str]:
        return [f"{brand}-1", f"{brand}-2"]

    items = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert items == ["구찌-1", "구찌-2", "샤넬-1", "샤넬-2"]


async def test_collect_brands_partial_failure_still_succeeds():
    async def crawl_brand(brand: str) -> list[str]:
        if brand == "구찌":
            raise RuntimeError("timeout")
        return [brand]

    items = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert items == ["샤넬"]


async def test_collect_brands_zero_items_is_valid_success():
    """
    요청/파싱이 정상 종료되어 []를 반환한 것은 실패가 아니다.
    이 경계조건이 없으면 실제 매물이 없는 상황을 장애로 오판하게 된다.
    """

    async def crawl_brand(brand: str) -> list[str]:
        return []

    items = await collect_brands(
        source_name="테스트",
        brands=("구찌", "샤넬"),
        crawl_brand=crawl_brand,
    )

    assert items == []


async def test_collect_brands_all_fail_raises():
    async def crawl_brand(brand: str) -> list[str]:
        raise RuntimeError(f"{brand} 차단")

    with pytest.raises(AllBrandsFailedError, match="모든 브랜드 크롤링 실패"):
        await collect_brands(
            source_name="테스트",
            brands=("구찌", "샤넬"),
            crawl_brand=crawl_brand,
        )


async def test_collect_brands_rejects_empty_brand_list():
    async def crawl_brand(brand: str) -> list[str]:
        return [brand]

    with pytest.raises(ValueError, match="브랜드"):
        await collect_brands(
            source_name="테스트",
            brands=(),
            crawl_brand=crawl_brand,
        )


async def test_collect_pages_collects_multiple_pages():
    async def collect_page(page_num: int) -> list[str]:
        return [f"item-{page_num}"]

    items = await collect_pages(
        source_name="테스트",
        max_pages=3,
        collect_page=collect_page,
    )

    assert items == ["item-1", "item-2", "item-3"]


async def test_collect_pages_partial_failure_continues():
    async def collect_page(page_num: int) -> list[str]:
        if page_num == 1:
            raise RuntimeError("timeout")
        return [f"item-{page_num}"]

    items = await collect_pages(
        source_name="테스트",
        max_pages=3,
        collect_page=collect_page,
    )

    assert items == ["item-2", "item-3"]


async def test_collect_pages_empty_page_is_valid_success_and_stops():
    called: list[int] = []

    async def collect_page(page_num: int) -> list[str]:
        called.append(page_num)
        return []

    items = await collect_pages(
        source_name="테스트",
        max_pages=3,
        collect_page=collect_page,
    )

    assert items == []
    assert called == [1]


async def test_collect_pages_all_fail_raises():
    async def collect_page(page_num: int) -> list[str]:
        raise RuntimeError(f"{page_num}페이지 timeout")

    with pytest.raises(AllPagesFailedError, match="모든 페이지 수집 실패"):
        await collect_pages(
            source_name="테스트",
            max_pages=3,
            collect_page=collect_page,
        )


async def test_collect_pages_rejects_non_positive_max_pages():
    async def collect_page(page_num: int) -> list[str]:
        return []

    with pytest.raises(ValueError, match="max_pages"):
        await collect_pages(
            source_name="테스트",
            max_pages=0,
            collect_page=collect_page,
        )
