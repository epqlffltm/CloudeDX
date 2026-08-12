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

logger = logging.getLogger(__name__)



class AllBrandsFailedError(RuntimeError):
    """한 사이트에서 시도한 모든 브랜드 수집이 예외로 실패했을 때 발생한다."""


class AllPagesFailedError(RuntimeError):
    """한 브랜드에서 시도한 모든 페이지 수집이 예외로 실패했을 때 발생한다."""


async def collect_brands[T](
    *,
    source_name: str,
    brands: Sequence[str],
    crawl_brand: Callable[[str], Awaitable[list[T]]],
) -> list[T]:
    """
    브랜드들을 순서대로 수집한다.

    한 브랜드가 실패해도 나머지는 계속한다. 단, 모든 브랜드가 예외로 실패했다면
    정상적인 "검색 결과 0건"과 구분할 수 있도록 예외를 올린다.

    crawl_brand()가 빈 리스트를 정상 반환한 경우는 성공이다. 실제로 매물이 0건일 수
    있기 때문에 결과 개수로 성공/실패를 판단하면 안 된다.
    """
    if not brands:
        raise ValueError("수집할 브랜드가 없습니다.")

    all_items: list[T] = []
    succeeded = 0
    errors: list[str] = []

    for brand in brands:
        try:
            items = await crawl_brand(brand)
        except Exception as exc:
            error = f"{brand}: {type(exc).__name__}: {exc}"
            errors.append(error)
            logger.warning("%s '%s' 크롤링 실패: %s", source_name, brand, exc)
            continue

        succeeded += 1
        all_items.extend(items)
        logger.info("%s '%s' %s건", source_name, brand, len(items))

    if succeeded == 0:
        raise AllBrandsFailedError(
            f"{source_name} 모든 브랜드 크롤링 실패: " + " / ".join(errors)
        )

    return all_items


async def collect_pages[T](
    *,
    source_name: str,
    max_pages: int,
    collect_page: Callable[[int], Awaitable[list[T]]],
    between_page_pause_seconds: float = 0.0,
) -> list[T]:
    """
    페이지들을 순서대로 수집한다.

    페이지 하나가 예외로 실패하면 다음 페이지를 시도한다. 하지만 모든 페이지가
    예외로 실패하면 빈 결과를 정상 성공처럼 반환하지 않고 예외를 올린다.

    반대로 페이지 요청/파싱이 정상 종료되어 빈 리스트가 나온 경우는 실제 검색 결과가
    없는 것으로 보고 정상 성공으로 처리하며 페이지 순회를 끝낸다.
    """
    if max_pages <= 0:
        raise ValueError("max_pages는 1 이상이어야 합니다.")

    all_items: list[T] = []
    succeeded = 0
    errors: list[str] = []

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

    return all_items