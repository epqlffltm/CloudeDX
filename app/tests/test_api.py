# app/tests/test_api.py

"""
JSON API 응답 계약 테스트.

여기서 검증하는 것들은 나중에 붙을 프론트엔드가 의존할 값이라, 필드가 사라지거나
의미가 바뀌면 프론트가 조용히 깨진다. 그래서 응답 형태를 명시적으로 단언한다.
"""

import pytest

from app.db import repository
from app.domain.models import CrawledItem


def make_item(url: str, **kwargs) -> CrawledItem:
    defaults = {
        "source": "당근마켓",
        "brand": "샤넬",
        "title": "샤넬 클래식 플랩",
        "price": "4,000,000원",
        "price_value": 4_000_000,
        "region": "서초구",
        "time_text": "3시간 전",
        "image_url": None,
        "is_sold": False,
    }

    return CrawledItem(url=url, **{**defaults, **kwargs})


async def test_list_returns_paged_envelope(client, session):
    await repository.upsert_items([make_item(f"https://ex.com/{i}") for i in range(5)])

    body = (await client.get("/api/crawled-items", params={"limit": 2})).json()

    assert body["total"] == 5
    assert body["count"] == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2


async def test_has_next_flag(client, session):
    """
    클라이언트가 offset + count < total을 직접 계산하게 하면 그 규칙이 프론트에
    복사된다. 서버가 판단해서 내려준다.
    """
    await repository.upsert_items([make_item(f"https://ex.com/{i}") for i in range(5)])

    first = (await client.get("/api/crawled-items", params={"limit": 3})).json()
    last = (
        await client.get("/api/crawled-items", params={"limit": 3, "offset": 3})
    ).json()

    assert first["has_next"] is True
    assert last["has_next"] is False


async def test_empty_result_has_next_false(client, session):
    body = (await client.get("/api/crawled-items")).json()

    assert body["total"] == 0
    assert body["has_next"] is False
    assert body["items"] == []


async def test_item_fields(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    item = (await client.get("/api/crawled-items")).json()["items"][0]

    # 프론트가 의존하는 필드들. 이름이 바뀌면 여기서 걸린다.
    expected = {
        "id",
        "source",
        "brand",
        "title",
        "price",
        "price_value",
        "region",
        "time_text",
        "posted_at",
        "image_url",
        "url",
        "is_sold",
        "first_seen_at",
        "last_seen_at",
    }

    assert set(item) == expected
    assert item["posted_at"] is not None


async def test_posted_at_null_when_site_omits_time(client, session):
    await repository.upsert_items([make_item("https://ex.com/1", time_text=None)])

    item = (await client.get("/api/crawled-items")).json()["items"][0]

    assert item["posted_at"] is None
    assert item["time_text"] is None


async def test_detail_and_404(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    item_id = (await client.get("/api/crawled-items")).json()["items"][0]["id"]

    found = await client.get(f"/api/crawled-items/{item_id}")
    missing = await client.get("/api/crawled-items/999999")

    assert found.status_code == 200
    assert found.json()["url"] == "https://ex.com/1"
    assert missing.status_code == 404
    assert "detail" in missing.json()


@pytest.mark.parametrize(
    "params",
    [
        {"min_price": 5000, "max_price": 100},  # 범위 모순
        {"limit": 0},  # 최소 미만
        {"limit": 500},  # 최대 초과
        {"offset": -1},  # 음수
    ],
)
async def test_invalid_params_rejected(client, params):
    """
    조건상 결과가 항상 0건인 요청은 빈 목록 대신 422를 준다. 데이터가 없는 건지
    조건이 잘못된 건지 구분할 수 있어야 한다.
    """
    response = await client.get("/api/crawled-items", params=params)

    assert response.status_code == 422


async def test_meta_returns_filter_options(client, session):
    """
    브랜드/수집처를 프론트에 하드코딩하면 brands.py를 고칠 때마다 양쪽을 고쳐야 한다.
    """
    body = (await client.get("/api/meta")).json()

    assert body["sources"] == ["당근마켓", "중고나라"]
    assert body["brands"] == ["구찌", "에르메스", "샤넬", "루이비통"]
    assert body["total_items"] == 0
    assert body["last_crawled_at"] is None


async def test_meta_reflects_stored_items(client, session):
    await repository.upsert_items([make_item(f"https://ex.com/{i}") for i in range(3)])

    body = (await client.get("/api/meta")).json()

    assert body["total_items"] == 3
    assert body["last_crawled_at"] is not None


async def test_board_pages_render(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    item_id = (await client.get("/api/crawled-items")).json()["items"][0]["id"]

    listing = await client.get("/board")
    detail = await client.get(f"/board/{item_id}")
    missing = await client.get("/board/999999")

    assert listing.status_code == 200
    assert "샤넬 클래식 플랩" in listing.text
    assert detail.status_code == 200
    # 원글 링크가 실제로 렌더링되는지 (템플릿 변수명이 어긋나면 조용히 빈칸이 된다)
    assert "https://ex.com/1" in detail.text
    assert missing.status_code == 404


async def test_board_filters_are_preserved_in_form(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    response = await client.get("/board", params={"brand": "샤넬", "search": "클래식"})

    assert 'value="샤넬" selected' in response.text
    assert 'value="클래식"' in response.text