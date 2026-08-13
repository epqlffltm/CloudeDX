# app/db/repository.py

"""
items 테이블에 대한 DB 접근을 한 곳에 모은 계층 (repository).

라우터는 "무엇을 원하는지"(필터 조건)만 넘기고, "어떻게 가져오는지"(SQL, 정렬, 카운트)는
전부 여기서 처리한다. JSON API(/crawled-items)와 HTML 게시판(/board)이 같은 함수를
호출하기 때문에, 두 화면의 결과가 갈라질 일이 없다.

- 조회 함수는 session을 인자로 받는다 (요청 단위 세션을 FastAPI가 Depends로 넣어준다).
- upsert_items는 요청과 무관한 백그라운드 크롤러가 호출하므로 세션을 직접 만든다.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import MISSING_THRESHOLD
from app.db.engine import async_session
from app.db.models import ItemRecord, PriceRecord, UnavailableReason
from app.domain.cleaning import clean_title
from app.domain.collection import CrawlScope
from app.domain.models import CrawledItem
from app.schemas.requests import CrawledItemFilterParams

# 한 INSERT 문에 넣을 최대 행 수. 너무 크면 바인드 파라미터가 폭증해서
# Postgres 한계(문당 65535개)에 걸린다. 컬럼 11개 기준 여유 있는 값으로 잡는다.
logger = logging.getLogger(__name__)

UPSERT_CHUNK_SIZE = 500

# 크롤링 결과에서 매번 덮어쓰는 컬럼들.
# first_seen_at과 posted_at은 여기 없다 — 둘 다 아래에서 따로 처리한다.
_UPDATABLE_COLUMNS = (
    "source",
    "brand",
    "search_brand",
    "clean_title",
    "model",
    "is_usable",
    "reject_reason",
    "title",
    "price",
    "region",
    "time_text",
    "image_url",
    "is_sold",
    "seller_type",
    # 다시 발견됐다는 뜻이므로 미발견 카운트를 되돌리고 활성 상태를 복구한다.
    # 판매완료로 다시 올라온 경우는 _dedupe_by_url이 is_active=False로 계산해 둔다.
    "missing_count",
    "is_active",
    "unavailable_at",
    "unavailable_reason",
)


def _apply_filters(stmt: Select, filters: CrawledItemFilterParams) -> Select:
    """
    필터 조건을 SELECT 문에 붙인다. 목록 조회와 건수 세기가 같은 조건을 써야 하므로
    함수로 빼서 양쪽이 공유한다 (조건이 어긋나면 total과 items가 안 맞게 된다).
    """
    if filters.source:
        stmt = stmt.where(ItemRecord.source == filters.source)

    if filters.brand:
        stmt = stmt.where(ItemRecord.brand == filters.brand)

    if filters.search:
        # ilike는 대소문자 무시 부분 일치. 한글에는 영향이 없지만 브랜드 영문 표기가
        # 섞여 들어올 수 있어서 like 대신 쓴다.
        stmt = stmt.where(ItemRecord.title.ilike(f"%{filters.search}%"))

    if filters.min_price is not None:
        stmt = stmt.where(ItemRecord.price_value >= filters.min_price)

    if filters.max_price is not None:
        stmt = stmt.where(ItemRecord.price_value <= filters.max_price)

    if filters.is_sold is not None:
        stmt = stmt.where(ItemRecord.is_sold == filters.is_sold)

    # 기본은 활성 매물만. 이미 사라진 매물을 가격비교 목록에 보여주면 잘못된 시세를 준다.
    # 판매완료 데이터가 필요한 쪽(실거래가 분석 등)은 include_inactive=true로 요청한다.
    if not filters.include_inactive:
        stmt = stmt.where(ItemRecord.is_active.is_(True))

    # 정제에서 걸러진 매물은 기본 조회에서 뺀다. 향수·신발·쇼핑백이 섞이면
    # "샤넬 최저가"가 카드지갑 가격이 되어 시세가 무너진다.
    if not filters.include_unusable:
        stmt = stmt.where(ItemRecord.is_usable.is_(True))

    if filters.model:
        stmt = stmt.where(ItemRecord.model == filters.model)

    return stmt


def _order_key():
    """
    목록 정렬 기준: 최근에 올라온 글이 위로.

    posted_at은 사이트가 시각을 표기하지 않으면 NULL이라, 그런 행은 first_seen_at으로
    대체해서 정렬한다(coalesce). 안 그러면 NULL 행이 전부 맨 뒤나 맨 앞으로 몰린다.

    id를 2차 정렬에 넣는 이유: "3일 전"으로 표기된 매물은 환산 결과가 초 단위까지
    같아질 수 있고, 그러면 정렬 순서가 매 요청마다 달라진다. 페이지를 넘길 때 같은
    매물이 두 번 보이거나 아예 건너뛰어지는 문제가 생긴다.
    """
    return (
        func.coalesce(ItemRecord.posted_at, ItemRecord.first_seen_at).desc(),
        ItemRecord.id.desc(),
    )


async def count_items(session: AsyncSession, filters: CrawledItemFilterParams) -> int:
    """필터 조건에 맞는 전체 건수. 페이지네이션의 total로 쓴다."""
    stmt = _apply_filters(select(ItemRecord.id), filters)
    result = await session.execute(select(func.count()).select_from(stmt.subquery()))

    return result.scalar_one()


async def list_items(
    session: AsyncSession, filters: CrawledItemFilterParams
) -> Sequence[ItemRecord]:
    """필터 + 페이지네이션을 적용한 매물 목록."""
    stmt = _apply_filters(select(ItemRecord), filters)
    stmt = stmt.order_by(*_order_key()).limit(filters.limit).offset(filters.offset)
    result = await session.execute(stmt)

    return result.scalars().all()


async def get_item(session: AsyncSession, item_id: int) -> ItemRecord | None:
    """PK 단건 조회. 없으면 None을 반환하고, 404 변환은 라우터가 담당한다."""
    return await session.get(ItemRecord, item_id)


async def get_last_crawled_at(session: AsyncSession) -> datetime | None:
    """
    가장 최근 크롤링 시각. 게시판 상단에 "마지막 수집: n분 전"을 보여주는 데 쓴다.
    데이터가 한 건도 없으면 None.
    """
    result = await session.execute(select(func.max(ItemRecord.last_seen_at)))

    return result.scalar_one_or_none()


def _dedupe_by_url(items: list[CrawledItem]) -> list[dict]:
    """
    url 기준으로 중복을 제거하고 dict 리스트로 바꾼다.

    한 라운드에서 브랜드별로 검색하다 보면 같은 매물이 여러 검색 결과에 걸릴 수 있다.
    그 상태로 한 INSERT 문에 넣으면 Postgres가
    "ON CONFLICT DO UPDATE command cannot affect row a second time" 에러를 낸다.
    같은 url이 여러 번 나오면 나중 것이 이긴다.
    """
    merged: dict[str, dict] = {}
    now = datetime.now(UTC)

    for item in items:
        # 저장 직전에 정제한다. 크롤러가 아니라 여기서 하는 이유는 두 사이트가
        # 같은 규칙을 거치게 하려는 것이고, 규칙을 고쳤을 때 재처리 지점이
        # 한 곳이어야 하기 때문이다.
        cleaned = clean_title(item.title, search_brand=item.brand)

        merged[item.url] = {
            "source": item.source,
            # 검색어가 아니라 제목에서 판정한 브랜드. 판정 실패 시 검색어를 남긴다.
            "brand": cleaned.brand or item.brand,
            "search_brand": item.brand,
            "clean_title": cleaned.clean_title,
            "model": cleaned.model,
            "is_usable": cleaned.is_usable,
            "reject_reason": cleaned.reject_reason,
            "title": item.title,
            "price": item.price,
            "price_value": item.price_value,
            "region": item.region,
            "time_text": item.time_text,
            "image_url": item.image_url,
            "url": item.url,
            "is_sold": item.is_sold,
            "seller_type": item.seller_type,
            "posted_at": item.posted_at,
            # 이번 라운드에서 봤으므로 미발견 카운트를 되돌린다. 판매완료 표기가
            # 있으면 그 자리에서 비활성 처리한다 — 사이트가 알려준 사실이라
            # 추정(missing)보다 신뢰도가 높다.
            "missing_count": 0,
            "is_active": not item.is_sold,
            "unavailable_at": now if item.is_sold else None,
            "unavailable_reason": UnavailableReason.SOLD if item.is_sold else None,
        }

    return list(merged.values())


async def upsert_items(items: list[CrawledItem]) -> int:
    """
    크롤링 결과를 url 기준으로 insert-or-update 하고, 처리한 건수를 반환한다.

    이미 있는 매물이면 가격/상태 등만 갱신하고 last_seen_at을 지금으로 찍는다.
    first_seen_at은 건드리지 않는다 — 이 값이 유지돼야 posted_at을 못 구한 매물의
    화면 표기를 대체할 수 있다.

    posted_at은 coalesce로 처리한다. 상대 시각 표기는 시간이 지날수록 거칠어지기
    때문이다("3시간 전"이 다음 날엔 "1일 전"이 된다). 한 번 값을 구했으면 그때 것이
    가장 정확하므로 유지하고, 아직 NULL인 행에만 새 값을 채운다.

    행을 하나씩 보내면 건수만큼 왕복이 생기므로 UPSERT_CHUNK_SIZE 단위로 묶어서 보낸다.
    전체가 한 트랜잭션이라, 중간에 실패하면 그 라운드 결과는 통째로 롤백된다.
    """
    rows = _dedupe_by_url(items)

    if not rows:
        return 0

    async with async_session() as session:
        for start in range(0, len(rows), UPSERT_CHUNK_SIZE):
            chunk = rows[start : start + UPSERT_CHUNK_SIZE]

            # upsert 전에 현재 가격을 읽어 둔다. ON CONFLICT DO UPDATE는 갱신 후의
            # 행만 돌려주므로, 이전 값을 알려면 미리 조회하는 수밖에 없다.
            # 청크당 SELECT 한 번이라 왕복 비용은 크지 않다.
            previous = await _fetch_current_prices(session, [r["url"] for r in chunk])

            stmt = pg_insert(ItemRecord).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[ItemRecord.url],
                set_={
                    **{col: getattr(stmt.excluded, col) for col in _UPDATABLE_COLUMNS},
                    "posted_at": func.coalesce(
                        ItemRecord.posted_at, stmt.excluded.posted_at
                    ),
                    # 파싱에 실패했다고 기존 가격을 지우지 않는다. 사이트 표기가
                    # 잠깐 달라져 값을 못 읽는 경우가 있는데, NULL로 덮으면
                    # 다음 라운드에 복구됐을 때 "가격이 바뀌었다"고 오해해
                    # 같은 값이 이력에 중복 기록된다.
                    "price_value": func.coalesce(
                        stmt.excluded.price_value, ItemRecord.price_value
                    ),
                    "last_seen_at": func.now(),
                },
            )

            await session.execute(stmt)

            # 이력은 upsert 뒤에 남긴다. 새 매물의 id가 있어야 하기 때문이다.
            await _record_price_changes(session, chunk, previous)

        await session.commit()

    return len(rows)


async def _fetch_current_prices(
    session: AsyncSession, urls: list[str]
) -> dict[str, tuple[int, int | None]]:
    """
    주어진 url들의 현재 (id, price_value)를 읽는다. 없는 매물은 빠진다.

    가격 이력을 남길지 판단하려면 갱신 전 값이 필요하다.
    """
    result = await session.execute(
        select(ItemRecord.url, ItemRecord.id, ItemRecord.price_value).where(
            ItemRecord.url.in_(urls)
        )
    )

    return {row.url: (row.id, row.price_value) for row in result}


async def _record_price_changes(
    session: AsyncSession,
    chunk: list[dict],
    previous: dict[str, tuple[int, int | None]],
) -> int:
    """
    가격이 바뀐 매물의 이력을 남기고 기록한 건수를 반환한다.

    남기는 경우는 둘이다.

    - **첫 관측** — 이전 기록이 없는 새 매물. 기준선이 있어야 "3개월째 그대로"를
      말할 수 있다. 변화만 남기면 한 번도 안 바뀐 매물은 이력이 비어 그 사실조차
      알 수 없다.
    - **가격 변동** — 이전 값과 다를 때.

    남기지 않는 경우:

    - **가격을 파싱하지 못했을 때(None)** — 값을 못 읽은 것과 가격이 바뀐 것은
      다르다. 사이트 표기가 잠깐 달라져 파싱이 실패하면 "가격이 사라졌다"는
      가짜 이력이 생기고, 다음 라운드에 복구되면 "가격이 돌아왔다"가 또 쌓인다.
    - **값이 같을 때** — 대부분의 라운드가 여기 해당한다. 이걸 걸러야 이력이
      의미 있는 크기로 유지된다.
    """
    to_insert = []

    for row in chunk:
        new_price = row.get("price_value")

        if new_price is None:
            continue

        existing = previous.get(row["url"])

        if existing is None:
            # 방금 insert된 새 매물. id를 모르므로 아래에서 한 번에 조회한다.
            to_insert.append((row["url"], new_price))
            continue

        item_id, old_price = existing

        if old_price != new_price:
            to_insert.append((row["url"], new_price))

    if not to_insert:
        return 0

    # url -> id 를 다시 조회한다. 새 매물은 방금 생겼고, 기존 매물도 같은 방법으로
    # 얻는 편이 두 경로를 나누는 것보다 단순하다.
    result = await session.execute(
        select(ItemRecord.url, ItemRecord.id).where(
            ItemRecord.url.in_([url for url, _ in to_insert])
        )
    )
    id_by_url = {row.url: row.id for row in result}

    records = [
        {"item_id": id_by_url[url], "price_value": price}
        for url, price in to_insert
        if url in id_by_url
    ]

    if records:
        await session.execute(pg_insert(PriceRecord).values(records))

    return len(records)


async def sweep_missing(scope: CrawlScope, seen_urls: set[str]) -> dict[str, int]:
    """
    이번 라운드에 보이지 않은 매물의 미발견 횟수를 올리고, 임계값을 넘으면 비활성 처리한다.

    처리한 건수를 {"marked": 카운트 올린 수, "deactivated": 비활성이 된 수}로 반환한다.

    **scope에 든 (수집처, 브랜드) 조합만 건드린다.** 크롤링이 실패했거나 수집 범위
    한계에 걸린 브랜드는 scope에 없으므로 그쪽 매물은 손대지 않는다. 못 본 것을
    사라진 것으로 오해하지 않기 위한 안전장치다.

    바로 지우지 않고 세는 이유:
        한 라운드에서 안 보였다는 것만으로는 판단할 수 없다. 사이트가 잠깐 느렸거나,
        검색 결과 순서가 흔들렸거나, 페이지 하나를 놓쳤을 수 있다. MISSING_THRESHOLD회
        연속으로 안 보여야 비활성으로 본다. 30분 주기 기준 3회면 1시간 30분이다.

    이미 비활성인 매물은 건드리지 않는다. 판매완료로 확정된 것을 미발견으로 덮어쓰면
    이유(unavailable_reason)가 사실과 달라진다.
    """
    if scope.is_empty():
        return {"marked": 0, "deactivated": 0}

    async with async_session() as session:
        base = (
            ItemRecord.source == scope.source,
            ItemRecord.brand.in_(scope.brands),
            ItemRecord.is_active.is_(True),
        )

        # seen_urls가 비어 있으면 NOT IN () 이 되어 SQL이 어색해지므로 조건을 나눈다.
        conditions = list(base)

        if seen_urls:
            conditions.append(ItemRecord.url.not_in(seen_urls))

        result = await session.execute(
            update(ItemRecord)
            .where(*conditions)
            .values(missing_count=ItemRecord.missing_count + 1)
            .returning(ItemRecord.id)
        )
        marked = len(result.scalars().all())

        # 임계값을 넘긴 것을 비활성으로 내린다. 위 UPDATE와 나눈 이유는 카운트를
        # 올린 뒤의 값으로 판단해야 하기 때문이다.
        result = await session.execute(
            update(ItemRecord)
            .where(
                ItemRecord.source == scope.source,
                ItemRecord.brand.in_(scope.brands),
                ItemRecord.is_active.is_(True),
                ItemRecord.missing_count >= MISSING_THRESHOLD,
            )
            .values(
                is_active=False,
                unavailable_at=func.now(),
                unavailable_reason=UnavailableReason.MISSING,
            )
            .returning(ItemRecord.id)
        )
        deactivated = len(result.scalars().all())

        await session.commit()

    if marked or deactivated:
        logger.info(
            "%s 미발견 처리: %d건 카운트 증가, %d건 비활성",
            scope.source,
            marked,
            deactivated,
        )

    return {"marked": marked, "deactivated": deactivated}


async def list_models(session: AsyncSession, brand: str | None = None) -> list[dict]:
    """
    수집된 모델과 각 모델의 매물 수·최저가를 반환한다.

    프론트의 모델 필터를 채우고, 시세 화면의 기초 자료가 된다. 정제를 통과한
    활성 매물만 센다 — 향수나 판매완료 매물이 섞이면 최저가가 실제와 달라진다.

    가격이 없는 매물(price_value가 NULL)은 최저가 계산에서 자연히 빠지지만
    매물 수에는 포함한다. "3건 있는데 가격은 2건만 안다"가 정직한 표현이다.
    """
    stmt = (
        select(
            ItemRecord.brand,
            ItemRecord.model,
            func.count().label("count"),
            func.min(ItemRecord.price_value).label("min_price"),
        )
        .where(
            ItemRecord.model.is_not(None),
            ItemRecord.is_usable.is_(True),
            ItemRecord.is_active.is_(True),
        )
        .group_by(ItemRecord.brand, ItemRecord.model)
        .order_by(func.count().desc())
    )

    if brand:
        stmt = stmt.where(ItemRecord.brand == brand)

    result = await session.execute(stmt)

    return [
        {
            "brand": row.brand,
            "model": row.model,
            "count": row.count,
            "min_price": row.min_price,
        }
        for row in result
    ]


async def get_price_history(session: AsyncSession, item_id: int) -> list[PriceRecord]:
    """
    한 매물의 가격 이력을 오래된 순으로 반환한다.

    변화 시점만 담겨 있으므로, 두 기록 사이의 기간은 그 가격이 유지된 구간이다.
    마지막 기록부터 지금까지가 현재 가격이 유지된 기간이 된다.
    """
    result = await session.execute(
        select(PriceRecord)
        .where(PriceRecord.item_id == item_id)
        .order_by(PriceRecord.recorded_at, PriceRecord.id)
    )

    return list(result.scalars().all())


async def list_price_drops(
    session: AsyncSession, *, days: int = 7, limit: int = 20
) -> list[dict]:
    """
    최근 값을 내린 매물을 낙폭이 큰 순으로 반환한다.

    이 프로젝트가 단순 목록과 갈리는 지점이다. 중고 거래에서 "값을 내렸다"는
    파는 쪽이 급해졌다는 신호이고, 사는 쪽에는 협상 여지가 있다는 뜻이다.
    매물 목록만으로는 알 수 없고 이력이 있어야 나온다.

    같은 매물의 첫 기록과 마지막 기록을 비교한다. 중간에 오르내렸더라도
    사는 사람이 관심 있는 건 "지금이 처음보다 싼가"이기 때문이다.
    """
    since = datetime.now(UTC) - timedelta(days=days)

    # 기간 안에 두 번 이상 기록된 매물만 대상. 한 번뿐이면 변화가 없었다는 뜻이다.
    first = (
        select(
            PriceRecord.item_id,
            func.min(PriceRecord.recorded_at).label("first_at"),
            func.max(PriceRecord.recorded_at).label("last_at"),
        )
        .where(PriceRecord.recorded_at >= since)
        .group_by(PriceRecord.item_id)
        .having(func.count() >= 2)
        .subquery()
    )

    old_price = aliased(PriceRecord)
    new_price = aliased(PriceRecord)

    stmt = (
        select(
            ItemRecord,
            old_price.price_value.label("old_price"),
            new_price.price_value.label("new_price"),
        )
        .join(first, first.c.item_id == ItemRecord.id)
        .join(
            old_price,
            (old_price.item_id == ItemRecord.id)
            & (old_price.recorded_at == first.c.first_at),
        )
        .join(
            new_price,
            (new_price.item_id == ItemRecord.id)
            & (new_price.recorded_at == first.c.last_at),
        )
        .where(
            new_price.price_value < old_price.price_value,
            ItemRecord.is_active.is_(True),
            ItemRecord.is_usable.is_(True),
        )
        .order_by((old_price.price_value - new_price.price_value).desc())
        .limit(limit)
    )

    result = await session.execute(stmt)

    return [
        {
            "item": row.ItemRecord,
            "old_price": row.old_price,
            "new_price": row.new_price,
            "drop_amount": row.old_price - row.new_price,
            "drop_rate": round(
                (row.old_price - row.new_price) / row.old_price * 100, 1
            ),
        }
        for row in result
    ]