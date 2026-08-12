# app/db/repository.py

"""
items 테이블에 대한 DB 접근을 한 곳에 모은 계층 (repository).

라우터는 "무엇을 원하는지"(필터 조건)만 넘기고, "어떻게 가져오는지"(SQL, 정렬, 카운트)는
전부 여기서 처리한다. JSON API(/crawled-items)와 HTML 게시판(/board)이 같은 함수를
호출하기 때문에, 두 화면의 결과가 갈라질 일이 없다.

- 조회 함수는 session을 인자로 받는다 (요청 단위 세션을 FastAPI가 Depends로 넣어준다).
- upsert_items는 요청과 무관한 백그라운드 크롤러가 호출하므로 세션을 직접 만든다.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import ItemRecord
from app.domain.models import CrawledItem
from app.schemas.requests import CrawledItemFilterParams

# 한 INSERT 문에 넣을 최대 행 수. 너무 크면 바인드 파라미터가 폭증해서
# Postgres 한계(문당 65535개)에 걸린다. 컬럼 11개 기준 여유 있는 값으로 잡는다.
UPSERT_CHUNK_SIZE = 500

# 크롤링 결과에서 매번 덮어쓰는 컬럼들.
# first_seen_at과 posted_at은 여기 없다 — 둘 다 아래에서 따로 처리한다.
_UPDATABLE_COLUMNS = (
    "source",
    "brand",
    "title",
    "price",
    "price_value",
    "region",
    "time_text",
    "image_url",
    "is_sold",
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

    for item in items:
        merged[item.url] = {
            "source": item.source,
            "brand": item.brand,
            "title": item.title,
            "price": item.price,
            "price_value": item.price_value,
            "region": item.region,
            "time_text": item.time_text,
            "image_url": item.image_url,
            "url": item.url,
            "is_sold": item.is_sold,
            "posted_at": item.posted_at,
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

            stmt = pg_insert(ItemRecord).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[ItemRecord.url],
                set_={
                    **{col: getattr(stmt.excluded, col) for col in _UPDATABLE_COLUMNS},
                    "posted_at": func.coalesce(
                        ItemRecord.posted_at, stmt.excluded.posted_at
                    ),
                    "last_seen_at": func.now(),
                },
            )

            await session.execute(stmt)

        await session.commit()

    return len(rows)