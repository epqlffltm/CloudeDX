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
from datetime import UTC, datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MISSING_THRESHOLD
from app.db.engine import async_session
from app.db.models import ItemRecord, UnavailableReason
from app.domain.cleaning import clean_title
from app.domain.collection import CrawlScope
from app.domain.models import CrawledItem
from app.schemas.requests import CrawledItemFilterParams

# 한 INSERT 문에 넣을 최대 행 수. 너무 크면 바인드 파라미터가 폭증해서
# Postgres 한계(문당 65535개)에 걸린다. 컬럼 20개 기준으로도 1만 개라 여유 있다.
logger = logging.getLogger(__name__)

UPSERT_CHUNK_SIZE = 500

# 크롤링 결과에서 매번 덮어쓰는 컬럼들.
# first_seen_at과 posted_at은 여기 없다 — 둘 다 아래에서 따로 처리한다.
_UPDATABLE_COLUMNS = (
    "source",
    "brand",
    "search_brand",
    "clean_title",
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

    if filters.category:
        stmt = stmt.where(ItemRecord.category == filters.category)

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

    # 기본은 활성 매물만. 이미 사라진 매물이 목록에 남으면 클릭이 죽은 링크로 이어지는데,
    # 원문 아웃링크가 서비스의 전부인 구조에서 죽은 링크는 치명적이다.
    # 판매완료까지 봐야 하는 쪽(정제 규칙 점검 등)은 include_inactive=true로 요청한다.
    if not filters.include_inactive:
        stmt = stmt.where(ItemRecord.is_active.is_(True))

    # 정제에서 걸러진 매물은 기본 조회에서 뺀다. "샤넬 가방" 목록에 향수·신발·
    # 쇼핑백이 섞이면 탐색 자체가 오염된다.
    if not filters.include_unusable:
        stmt = stmt.where(ItemRecord.is_usable.is_(True))

    return stmt


def _order_key(order_by: str = "latest"):
    """
    목록 정렬 기준. 기본은 최근에 올라온 글이 위로.

    posted_at은 사이트가 시각을 표기하지 않으면 NULL이라, 그런 행은 first_seen_at으로
    대체해서 정렬한다(coalesce). 안 그러면 NULL 행이 전부 맨 뒤나 맨 앞으로 몰린다.

    가격 정렬(price_asc/price_desc)에서 price_value NULL(가격 미상)은 방향과 무관하게
    nulls_last로 맨 뒤에 보낸다 — 낮은 가격순을 물었는데 가격 없는 매물이 첫 화면을
    채우면 정렬이 고장 난 것처럼 보인다.

    id를 2차 정렬에 넣는 이유: "3일 전"으로 표기된 매물은 환산 결과가 초 단위까지
    같아질 수 있고(가격도 같은 값이 흔하다), 그러면 정렬 순서가 매 요청마다 달라진다.
    페이지를 넘길 때 같은 매물이 두 번 보이거나 아예 건너뛰어지는 문제가 생긴다.
    """
    posted = func.coalesce(ItemRecord.posted_at, ItemRecord.first_seen_at)
    match order_by:
        case "oldest":
            return (posted.asc(), ItemRecord.id.asc())
        case "price_asc":
            return (ItemRecord.price_value.asc().nulls_last(), ItemRecord.id.desc())
        case "price_desc":
            return (ItemRecord.price_value.desc().nulls_last(), ItemRecord.id.desc())
        case _:
            return (posted.desc(), ItemRecord.id.desc())


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
    stmt = stmt.order_by(*_order_key(filters.order_by)).limit(filters.limit).offset(filters.offset)
    result = await session.execute(stmt)

    return result.scalars().all()


CATEGORIES: tuple[str, ...] = ("bag", "watch", "jewelry", "apparel", "shoes")


async def count_by_category(session: AsyncSession) -> dict[str, int]:
    """
    카테고리별 노출 가능(활성 + 정제 통과) 매물 수. 화면의 카테고리 카드가 쓴다.

    5종 키를 항상 0으로 깔고 시작한다 — 아직 한 건도 없는 카테고리도 카드에는
    "0개"로 정직하게 표시돼야 하고, 키가 아예 빠지면 프론트가 undefined를 다룬다.
    'unknown'(분류 실패분)은 노출 대상이 아니라 여기 안 나온다.
    """
    stmt = (
        select(ItemRecord.category, func.count())
        .where(ItemRecord.is_active.is_(True), ItemRecord.is_usable.is_(True))
        .group_by(ItemRecord.category)
    )
    result = await session.execute(stmt)

    counts = dict.fromkeys(CATEGORIES, 0)
    counts.update({cat: n for cat, n in result.all() if cat in counts})

    return counts


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
            # 분류 실패는 NULL이 아니라 'unknown'이다 — 컬럼이 NOT NULL(기본 'bag')로
            # 이미 배포돼 있어서, 센티널을 쓰면 마이그레이션 없이 확장된다.
            "category": cleaned.category or "unknown",
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


async def upsert_items(
    items: list[CrawledItem],
    session: AsyncSession | None = None,
) -> int:
    """
    크롤링 결과를 url 기준으로 insert-or-update 하고, 처리한 건수를 반환한다.

    session 을 주면 그것을 쓰고, 없으면 자체 세션을 연다. 기본값이 None 인 이유는
    호출부 대부분(크롤러, 테스트)이 세션을 들고 있지 않기 때문이다.

    세션을 넘길 수 있어야 하는 이유는 커넥션 횟수다. 업로드 라우터는 이미 Depends 로
    세션을 하나 받아 두는데, 여기서 또 열면 한 요청이 커넥션을 두 번 맺는다. 평소에는
    풀에서 꺼내 오니 티가 안 나지만 DB가 죽어 있을 때 드러난다 — 접속 시도마다
    connect timeout(10초)을 통째로 기다려서, 응답이 30초 넘게 매달린다.

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

    if session is not None:
        await _upsert_rows(session, rows)
        return len(rows)

    async with async_session() as owned:
        await _upsert_rows(owned, rows)

    return len(rows)


async def _upsert_rows(session: AsyncSession, rows: list[dict]) -> None:
    """UPSERT 본체. 세션의 출처와 무관하게 같은 SQL을 돌린다."""
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
                # 파싱에 실패했다고 기존 가격을 지우지 않는다. 사이트 표기가
                # 잠깐 달라져 값을 못 읽는 경우가 있는데, NULL로 덮으면 그
                # 라운드 동안 화면이 '가격 미상'으로 깜빡이고, 가격 필터가 걸린
                # 조회에서는 매물이 사라졌다 나타나기를 반복한다.
                "price_value": func.coalesce(
                    stmt.excluded.price_value, ItemRecord.price_value
                ),
                "last_seen_at": func.now(),
            },
        )

        await session.execute(stmt)

    await session.commit()


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
            # 검색 잡의 카테고리 안에서만 판정한다. "샤넬 가방" 라운드가
            # 샤넬 시계를 "안 보였다"고 오판하는 것을 막는 조건이다.
            ItemRecord.category == scope.category,
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
