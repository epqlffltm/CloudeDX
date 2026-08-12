# app/tests/test_repository.py

"""
app.db.repository 테스트.

여기서 검증하는 것 대부분이 Postgres 고유 동작이라 실제 DB에 붙어서 돌린다
(conftest.py의 설명 참고). 특히 upsert는 `INSERT ... ON CONFLICT DO UPDATE`를 쓰고,
정렬은 `COALESCE`와 timestamptz 비교에 의존한다.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import repository
from app.db.models import ItemRecord
from app.domain.models import CrawledItem
from app.schemas.requests import CrawledItemFilterParams


def make_item(
    *,
    url: str,
    source: str = "당근마켓",
    brand: str = "샤넬",
    title: str = "샤넬 클래식 플랩",
    price_value: int | None = 4_000_000,
    time_text: str | None = "3시간 전",
    is_sold: bool = False,
) -> CrawledItem:
    return CrawledItem(
        source=source,
        brand=brand,
        title=title,
        price=f"{price_value:,}원" if price_value else None,
        price_value=price_value,
        region="서초구",
        time_text=time_text,
        image_url=None,
        url=url,
        is_sold=is_sold,
    )


async def test_upsert_inserts_new_items(session):
    saved = await repository.upsert_items(
        [make_item(url="https://ex.com/1"), make_item(url="https://ex.com/2")]
    )

    assert saved == 2
    assert await repository.count_items(session, CrawledItemFilterParams()) == 2


async def test_upsert_dedupes_within_batch(session):
    """
    같은 url이 한 배치에 두 번 들어오면 Postgres가
    "ON CONFLICT DO UPDATE command cannot affect row a second time" 에러를 낸다.
    _dedupe_by_url이 미리 정리하므로 예외 없이 마지막 것이 남아야 한다.
    """
    saved = await repository.upsert_items(
        [
            make_item(url="https://ex.com/1", title="샤넬 클래식 처음"),
            make_item(url="https://ex.com/1", title="샤넬 클래식 나중"),
        ]
    )

    assert saved == 1

    rows = await repository.list_items(session, CrawledItemFilterParams())
    assert rows[0].title == "샤넬 클래식 나중"


async def test_upsert_preserves_first_seen_at(session):
    """
    재수집해도 first_seen_at은 그대로여야 한다. 이 값이 유지돼야 등록 시각을 구하지
    못한 매물의 화면 표기를 대체할 수 있다.
    """
    await repository.upsert_items([make_item(url="https://ex.com/1")])
    original = (await repository.list_items(session, CrawledItemFilterParams()))[0]
    item_id = original.id
    first_seen = original.first_seen_at

    await repository.upsert_items(
        [make_item(url="https://ex.com/1", title="샤넬 클래식 가격 내림", price_value=3_000_000)]
    )

    session.expire_all()
    updated = await repository.get_item(session, item_id)

    assert updated.first_seen_at == first_seen
    assert updated.last_seen_at > first_seen
    assert updated.price_value == 3_000_000
    assert updated.title == "샤넬 클래식 가격 내림"


async def test_upsert_keeps_earliest_posted_at(session):
    """
    posted_at은 COALESCE로 처리한다. 상대 시각 표기는 시간이 지날수록 거칠어지므로
    (오늘 '3시간 전' -> 내일 '1일 전') 처음 구한 값이 가장 정확하다.
    """
    await repository.upsert_items(
        [make_item(url="https://ex.com/1", time_text="3시간 전")]
    )
    first = (await repository.list_items(session, CrawledItemFilterParams()))[0]
    # expire_all() 이후에는 ORM 객체의 속성 접근이 지연 로딩을 유발하므로 미리 읽어둔다.
    item_id = first.id
    original_posted = first.posted_at

    assert original_posted is not None

    await repository.upsert_items(
        [make_item(url="https://ex.com/1", time_text="5일 전")]
    )

    session.expire_all()
    updated = await repository.get_item(session, item_id)

    assert updated.posted_at == original_posted


async def test_upsert_fills_null_posted_at_later(session):
    """
    반대로 아직 NULL인 행에는 새 값이 채워져야 한다. 컬럼을 추가한 뒤 크롤링을
    한 바퀴 돌리면 기존 행도 자동으로 채워지는 것이 이 동작에 달려 있다.
    """
    await repository.upsert_items([make_item(url="https://ex.com/1", time_text=None)])
    row = (await repository.list_items(session, CrawledItemFilterParams()))[0]
    item_id = row.id

    assert row.posted_at is None

    await repository.upsert_items(
        [make_item(url="https://ex.com/1", time_text="2시간 전")]
    )

    session.expire_all()
    updated = await repository.get_item(session, item_id)

    assert updated.posted_at is not None


async def test_upsert_empty_list_is_noop(session):
    assert await repository.upsert_items([]) == 0


@pytest.mark.parametrize(
    ("filters", "expected_urls"),
    [
        (CrawledItemFilterParams(source="중고나라"), {"https://ex.com/2"}),
        (CrawledItemFilterParams(brand="구찌"), {"https://ex.com/2"}),
        (CrawledItemFilterParams(min_price=5_000_000), {"https://ex.com/2"}),
        # ex.com/3은 판매완료라 기본 조회에서 빠진다. 아래 include_inactive 테스트 참고.
        (CrawledItemFilterParams(max_price=1_000_000), set()),
        (CrawledItemFilterParams(search="클래식"), {"https://ex.com/1"}),
        (
            CrawledItemFilterParams(is_sold=True, include_inactive=True),
            {"https://ex.com/3"},
        ),
        (
            CrawledItemFilterParams(search="클래식", include_inactive=True),
            {"https://ex.com/1", "https://ex.com/3"},
        ),
    ],
)
async def test_filters(session, filters, expected_urls):
    await repository.upsert_items(
        [
            make_item(url="https://ex.com/1", price_value=4_000_000),
            make_item(
                url="https://ex.com/2",
                source="중고나라",
                brand="구찌",
                title="구찌 마몬트",
                price_value=6_000_000,
            ),
            make_item(url="https://ex.com/3", price_value=900_000, is_sold=True),
        ]
    )

    rows = await repository.list_items(session, filters)

    assert {row.url for row in rows} == expected_urls
    assert await repository.count_items(session, filters) == len(expected_urls)


async def test_price_filter_excludes_unparsed(session):
    """
    가격 파싱에 실패한 매물(price_value가 NULL)은 가격 조건을 걸면 제외돼야 한다.
    "가격 미상"을 조건에 맞다고 보면 최저가 비교 결과가 오염된다.
    """
    await repository.upsert_items(
        [
            make_item(url="https://ex.com/1", price_value=1_000_000),
            make_item(url="https://ex.com/2", price_value=None),
        ]
    )

    rows = await repository.list_items(
        session, CrawledItemFilterParams(min_price=0, max_price=99_999_999)
    )

    assert {row.url for row in rows} == {"https://ex.com/1"}


async def test_list_sorted_by_posted_at_desc(session):
    await repository.upsert_items(
        [
            make_item(url="https://ex.com/old", time_text="5일 전"),
            make_item(url="https://ex.com/new", time_text="1시간 전"),
            make_item(url="https://ex.com/mid", time_text="1일 전"),
        ]
    )

    rows = await repository.list_items(session, CrawledItemFilterParams())

    assert [row.url for row in rows] == [
        "https://ex.com/new",
        "https://ex.com/mid",
        "https://ex.com/old",
    ]


async def test_null_posted_at_falls_back_to_first_seen_at(session):
    """
    posted_at이 NULL인 행을 first_seen_at으로 대체하지 않으면 그 행들이 전부 맨 뒤나
    맨 앞으로 몰린다. 방금 수집한 행이므로 5일 전 글보다는 위에 와야 한다.
    """
    await repository.upsert_items(
        [
            make_item(url="https://ex.com/old", time_text="5일 전"),
            make_item(url="https://ex.com/unknown", time_text=None),
        ]
    )

    rows = await repository.list_items(session, CrawledItemFilterParams())

    assert rows[0].url == "https://ex.com/unknown"


async def test_pagination_does_not_repeat_or_skip(session):
    """
    같은 라운드에서 들어온 행들은 환산된 posted_at이 초 단위까지 같아질 수 있다.
    id를 2차 정렬에 넣지 않으면 페이지를 넘길 때 같은 매물이 두 번 보이거나
    아예 건너뛰어진다.
    """
    await repository.upsert_items(
        [make_item(url=f"https://ex.com/{i}", time_text="1일 전") for i in range(10)]
    )

    page1 = await repository.list_items(
        session, CrawledItemFilterParams(limit=4, offset=0)
    )
    page2 = await repository.list_items(
        session, CrawledItemFilterParams(limit=4, offset=4)
    )
    page3 = await repository.list_items(
        session, CrawledItemFilterParams(limit=4, offset=8)
    )

    seen = [row.url for row in (*page1, *page2, *page3)]

    assert len(seen) == 10
    assert len(set(seen)) == 10


async def test_get_item_returns_none_for_missing(session):
    assert await repository.get_item(session, 999_999) is None


async def test_get_last_crawled_at(session):
    assert await repository.get_last_crawled_at(session) is None

    await repository.upsert_items([make_item(url="https://ex.com/1")])

    last = await repository.get_last_crawled_at(session)

    assert last is not None
    assert datetime.now(UTC) - last < timedelta(minutes=1)


async def test_large_batch_is_chunked(session):
    """
    UPSERT_CHUNK_SIZE(500)를 넘는 배치가 여러 문으로 나뉘어도 전부 저장돼야 한다.
    한 문에 몰아넣으면 바인드 파라미터가 Postgres 한계(65535)에 걸린다.
    """
    items = [make_item(url=f"https://ex.com/bulk/{i}") for i in range(1200)]

    saved = await repository.upsert_items(items)

    assert saved == 1200

    result = await session.execute(select(ItemRecord.id))
    assert len(result.scalars().all()) == 1200