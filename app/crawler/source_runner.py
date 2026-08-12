# app/crawler/source_runner.py

"""
사이트 내부 수집 정책.

runner.py는 "사이트 작업 여러 개를 한 라운드에서 어떻게 실행할지"를 다루고,
이 파일은 그보다 한 단계 아래인 "한 사이트 안에서 브랜드/페이지 일부가 실패했을 때
어떻게 판단할지"를 다룬다.

Playwright를 임포트하지 않는다. 그래서 실제 브라우저 없이도 다음 경계조건을 CI에서
검증할 수 있다.

- 브랜드 하나 실패 -> 나머지 브랜드 계속
- 모든 브랜드 실패 -> 사이트 작업 실패
- 페이지 하나 실패 -> 다음 페이지 계속
- 모든 페이지 실패 -> 해당 브랜드 수집 실패
- 정상 요청 결과가 0건 -> 실패가 아니라 정상 성공
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.domain.collection import Collection

logger = logging.getLogger(__name__)



class AllBrandsFailedError(RuntimeError):
    """한 사이트에서 시도한 모든 브랜드 수집이 예외로 실패했을 때 발생한다."""


class AllPagesFailedError(RuntimeError):
    """한 브랜드에서 시도한 모든 페이지 수집이 예외로 실패했을 때 발생한다."""


async def collect_brands[T](
    *,
    source_name: str,
    brands: Sequence[str],
    crawl_brand: Callable[[str], Awaitable[Collection[T]]],
) -> tuple[Collection[T], set[str]]:
    """
    브랜드들을 순서대로 수집한다. 결과와 함께 **완전히 훑은 브랜드 집합**을 반환한다.

    한 브랜드가 실패해도 나머지는 계속한다. 단, 모든 브랜드가 예외로 실패했다면
    정상적인 "검색 결과 0건"과 구분할 수 있도록 예외를 올린다.

    완전히 훑은 브랜드에만 미발견 판정을 적용할 수 있다. 두 경우를 제외한다.

    - 예외로 실패한 브랜드 — 못 본 매물이 있다.
    - **성공했지만 0건인 브랜드** — 이게 함정이다. 봇 감지로 빈 페이지를 받으면
      예외 없이 0건으로 정상 종료된다. 실제 로그에서 "당근마켓 '루이비통' 0건"이
      나온 적이 있는데, 나머지 브랜드는 60건씩이었다. 이걸 "루이비통 매물이 전부
      사라졌다"로 해석하면 해당 브랜드 매물이 전량 비활성 처리된다.
      진짜 0건이면 다음 라운드에도 0건일 테니, 며칠치 기록으로 판단하는 편이 안전하다.
    """
    if not brands:
        raise ValueError("수집할 브랜드가 없습니다.")

    collected: Collection[T] = Collection()
    complete_brands: set[str] = set()
    succeeded = 0
    errors: list[str] = []

    for brand in brands:
        try:
            result = await crawl_brand(brand)
        except Exception as exc:
            error = f"{brand}: {type(exc).__name__}: {exc}"
            errors.append(error)
            logger.warning("%s '%s' 크롤링 실패: %s", source_name, brand, exc)
            continue

        succeeded += 1
        collected.items.extend(result.items)

        if result.complete and result.items:
            complete_brands.add(brand)
        elif not result.items:
            logger.warning(
                "%s '%s' 0건. 차단 가능성이 있어 미발견 판정에서 제외합니다.",
                source_name,
                brand,
            )
        else:
            logger.info(
                "%s '%s' 수집 범위 한계에 걸려 미발견 판정에서 제외합니다.",
                source_name,
                brand,
            )

        logger.info("%s '%s' %s건", source_name, brand, len(result.items))

    if succeeded == 0:
        raise AllBrandsFailedError(
            f"{source_name} 모든 브랜드 크롤링 실패: " + " / ".join(errors)
        )

    collected.complete = len(complete_brands) == len(brands)

    return collected, complete_brands


async def collect_pages[T](
    *,
    source_name: str,
    max_pages: int,
    collect_page: Callable[[int], Awaitable[list[T]]],
    between_page_pause_seconds: float = 0.0,
) -> Collection[T]:
    """
    페이지들을 순서대로 수집하고, **마지막 페이지까지 도달했는지**를 함께 반환한다.

    페이지 하나가 예외로 실패하면 다음 페이지를 시도한다. 하지만 모든 페이지가
    예외로 실패하면 빈 결과를 정상 성공처럼 반환하지 않고 예외를 올린다.

    완전성(complete) 판정:
        빈 페이지를 만나서 멈췄으면 끝까지 본 것이다 — 그 뒤로는 매물이 없다.
        max_pages를 다 쓰고도 계속 매물이 나왔다면 아직 남아 있다는 뜻이므로 불완전.
        페이지 오류가 하나라도 있었으면 그 페이지의 매물을 못 봤으므로 불완전.

    이 구분이 필요한 이유는 미발견 판정 때문이다. 중고나라를 브랜드당 3페이지만 긁는데,
    4페이지로 밀린 매물을 "사라졌다"고 판단하면 멀쩡한 매물이 비활성 처리된다.
    """
    if max_pages <= 0:
        raise ValueError("max_pages는 1 이상이어야 합니다.")

    all_items: list[T] = []
    succeeded = 0
    errors: list[str] = []
    reached_end = False

    for page_num in range(1, max_pages + 1):
        try:
            page_items = await collect_page(page_num)
        except Exception as exc:
            error = f"{page_num}페이지: {type(exc).__name__}: {exc}"
            errors.append(error)
            logger.warning(
                "%s %d 페이지 진행 중 오류, 다음 페이지로 건너뜀: %s",
                source_name,
                page_num,
                exc,
            )
            continue

        succeeded += 1

        if not page_items:
            logger.info(
                "%s %d 페이지에서 상품을 찾지 못해 수집을 마칩니다.",
                source_name,
                page_num,
            )
            reached_end = True
            break

        all_items.extend(page_items)
        logger.info(
            "%s %d 페이지 %d건 (누적: %d건)",
            source_name,
            page_num,
            len(page_items),
            len(all_items),
        )

        if page_num < max_pages and between_page_pause_seconds > 0:
            await asyncio.sleep(between_page_pause_seconds)

    if succeeded == 0:
        raise AllPagesFailedError(
            f"{source_name} 모든 페이지 수집 실패: " + " / ".join(errors)
        )

    complete = reached_end and not errors

    if not complete and not errors:
        logger.info(
            "%s %d페이지 한계에 도달했습니다. 더 남은 매물이 있을 수 있습니다.",
            source_name,
            max_pages,
        )

    return Collection(items=all_items, complete=complete)