# app/tests/test_admin_overview.py
"""관리자 overview의 권한과 핵심 집계 계약."""

from app.db import repository
from app.domain.models import CrawledItem


def _item(url: str, title: str, *, sold: bool = False):
    return CrawledItem(
        source="중고나라",
        brand="샤넬",
        title=title,
        price="1,000,000원",
        price_value=1_000_000,
        region=None,
        time_text=None,
        image_url=None,
        url=url,
        is_sold=sold,
    )


async def _login(client, username: str, password: str):
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


async def test_overview_requires_admin(client):
    assert (await client.get("/api/admin/overview")).status_code == 401

    await _login(client, "client", "client1234")
    assert (await client.get("/api/admin/overview")).status_code == 403


async def test_overview_counts_visible_inactive_and_unusable(client, session):
    await repository.upsert_items(
        [
            _item("https://admin.example/visible", "샤넬 클래식 플랩백"),
            _item("https://admin.example/inactive", "샤넬 클래식 플랩백 판매완료", sold=True),
            _item("https://admin.example/unusable", "샤넬 넘버5 향수 미개봉"),
        ],
        session=session,
    )

    await _login(client, "admin", "admin1234")
    response = await client.get("/api/admin/overview")

    assert response.status_code == 200
    body = response.json()

    assert body["items"]["stored"] == 3
    assert body["items"]["visible"] == 1
    assert body["items"]["inactive"] == 1
    assert body["items"]["unusable"] == 1
    assert body["items"]["by_source"] == {"중고나라": 1}
    assert body["items"]["by_category"]["bag"] == 1
    assert body["items"]["unavailable_reasons"]["sold"] == 1
    assert body["viewer"] == {"username": "admin", "role": "admin"}
