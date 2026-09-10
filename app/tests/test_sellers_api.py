# app/tests/test_sellers_api.py
"""입점 판매자 조회와 노출 가능 매물 수 집계 테스트."""

from sqlalchemy import update

from app.db import repository
from app.db.models import ItemRecord, Seller
from app.domain.models import CrawledItem
from app.domain.sources import UPLOAD
from app.tests.sellers import make_seller


def _item(url: str, title: str, *, sold: bool = False):
    return CrawledItem(
        source=UPLOAD,
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


async def test_seller_response_and_visible_item_count(client, session):
    seller_id = await make_seller(session, "청담 테스트")
    seller = await session.get(Seller, seller_id)
    seller.has_store = True
    seller.address = "서울특별시 강남구 테스트로 1"
    seller.latitude = 37.52
    seller.longitude = 127.05
    seller.description = "테스트 판매자"
    seller.photo_url = "img/sellers/test.jpg"
    await session.commit()

    other_seller_id = await make_seller(session, "다른 상사")

    visible = "https://seller.example/visible"
    inactive = "https://seller.example/inactive"
    unusable = "https://seller.example/unusable"
    other = "https://seller.example/other"

    await repository.upsert_items(
        [
            _item(visible, "샤넬 클래식 플랩백 미디움"),
            _item(inactive, "샤넬 클래식 플랩백 판매완료", sold=True),
            _item(unusable, "샤넬 넘버5 향수 미개봉"),
            _item(other, "샤넬 클래식 플랩백 스몰"),
        ],
        session=session,
    )

    await session.execute(
        update(ItemRecord).where(ItemRecord.url.in_([visible, inactive, unusable])).values(
            seller_id=seller_id
        )
    )
    await session.execute(
        update(ItemRecord).where(ItemRecord.url == other).values(seller_id=other_seller_id)
    )
    await session.commit()

    response = await client.get(f"/api/sellers/{seller_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seller_id
    assert body["name"] == "청담 테스트"
    assert body["has_store"] is True
    assert body["address"] == "서울특별시 강남구 테스트로 1"
    assert body["photo_url"] == "img/sellers/test.jpg"
    assert body["item_count"] == 1


async def test_missing_seller_is_404(client):
    response = await client.get("/api/sellers/2147483647")

    assert response.status_code == 404


async def test_online_only_seller_can_have_null_location(client, session):
    seller_id = await make_seller(session, "온라인 테스트")

    response = await client.get(f"/api/sellers/{seller_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["has_store"] is False
    assert body["address"] is None
    assert body["latitude"] is None
    assert body["longitude"] is None
