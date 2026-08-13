# app/tests/test_products.py

"""
프론트엔드용 상품 API 테스트.

이 계층은 **우리 도메인(매물)과 프론트 계약(상품) 사이의 어댑터**다. 두 모양이
다른 이유는 프론트가 상품 단위로 설계됐고 우리는 매물 단위로 수집하기 때문이다.

여기서 지키려는 것은 두 가지다.

1. **없는 데이터를 지어내지 않는다.** 프론트 타입에는 views·likes·grade가 있었는데
   사이트가 주지 않는 값이라 뺐다. 모델명도 추출 실패 시 null로 두고 제목으로
   채우지 않는다 — 나중에 진짜 모델 그룹화를 할 때 가짜 모델명이 섞이면 그룹이
   어긋난다.
2. **두 엔드포인트가 같은 데이터를 본다.** /api/products와 /api/crawled-items가
   다른 조건을 쓰면 "목록에는 있는데 상품에는 없는" 상황이 생긴다.
"""

from app.db import repository
from app.domain.models import CrawledItem
from app.domain.seller import SellerType


def make_item(
    url: str,
    *,
    price: int | None = 4_000_000,
    title: str = "샤넬 클래식 플랩 캐비어",
    source: str = "중고나라",
    seller_type: str | None = None,
    is_sold: bool = False,
):
    return CrawledItem(
        source=source,
        brand="샤넬",
        title=title,
        price=f"{price:,}원" if price else None,
        price_value=price,
        region="서초구",
        time_text="3시간 전",
        image_url="https://img.example.com/1.jpg",
        url=url,
        is_sold=is_sold,
        seller_type=seller_type,
    )


async def test_maps_listing_to_product(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])

    body = (await client.get("/api/products")).json()
    product = body["items"][0]

    assert product["id"].startswith("item-")
    assert product["brand"] == "샤넬"
    assert product["korean_name"] == "샤넬 클래식 플랩 캐비어"
    assert product["lowest_price"] == 4_000_000
    assert product["thumbnail_url"] == "https://img.example.com/1.jpg"


async def test_platform_prices_has_one_entry(client, session):
    """
    지금은 매물 하나가 상품 하나다. 프론트의 mock도 62개 중 57개가 플랫폼
    하나짜리였다 — 겉모습만 상품이고 실제로는 매물이었다.

    모델 그룹화를 도입하면 여기가 여러 개가 된다. 그때 프론트가 이미 배열을
    다루고 있으므로 수정이 필요 없다.
    """
    await repository.upsert_items([make_item("https://ex.com/1")])

    product = (await client.get("/api/products")).json()["items"][0]

    assert len(product["platform_prices"]) == 1
    assert product["platform_prices"][0]["platform_name"] == "중고나라"
    assert product["platform_prices"][0]["link_url"] == "https://ex.com/1"


async def test_model_name_is_null_when_unknown(client, session):
    """
    제목에서 모델을 특정하지 못하면 null이다. 제목으로 채우면 나중에 진짜
    그룹화를 할 때 가짜 모델명이 섞여 그룹이 어긋난다.
    """
    await repository.upsert_items(
        [make_item("https://ex.com/1", title="샤넬 가방 팝니다")]
    )

    product = (await client.get("/api/products")).json()["items"][0]

    assert product["model_name"] is None
    assert product["korean_name"] == "샤넬 가방 팝니다"


async def test_model_name_when_known(client, session):
    await repository.upsert_items(
        [make_item("https://ex.com/1", title="샤넬 클래식 플랩 캐비어")]
    )

    product = (await client.get("/api/products")).json()["items"][0]

    assert product["model_name"] == "클래식"


async def test_spam_tail_is_stripped_from_display_name(client, session):
    """
    화면에 보여줄 제목에는 검색용 브랜드 나열이 없어야 한다.
    """
    title = "샤넬 클래식 캐비어 클러치백 정품S급(감정O)구찌프라다루이비통디올고야드샤넬셀린느"
    await repository.upsert_items([make_item("https://ex.com/1", title=title)])

    product = (await client.get("/api/products")).json()["items"][0]

    assert "프라다" not in product["korean_name"]
    assert product["korean_name"].startswith("샤넬 클래식")


# ---------------------------------------------------------------------------
# 판매자 유형 — null의 의미가 중요하다
# ---------------------------------------------------------------------------


async def test_certified_seller(client, session):
    await repository.upsert_items(
        [make_item("https://ex.com/1", seller_type=SellerType.CERTIFIED)]
    )

    product = (await client.get("/api/products")).json()["items"][0]

    assert product["platform_prices"][0]["seller_type"] == "certified"
    assert "인증셀러" in product["tags"]


async def test_seller_type_null_means_unknown(client, session):
    """
    당근마켓에는 인증 배지 체계가 없다. 전부 'individual'로 적으면 "당근은
    개인거래만"이라는 잘못된 사실이 데이터에 박힌다. null은 "모른다"는 뜻이다.
    """
    await repository.upsert_items(
        [make_item("https://ex.com/1", source="당근마켓", seller_type=None)]
    )

    product = (await client.get("/api/products")).json()["items"][0]

    assert product["platform_prices"][0]["seller_type"] is None
    assert "인증셀러" not in product["tags"]


# ---------------------------------------------------------------------------
# 우리만 있는 데이터
# ---------------------------------------------------------------------------


async def test_listed_days_is_at_least_one(client, session):
    """방금 수집한 매물도 1일째다. 0일이면 화면에 "0일째"라고 나온다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    product = (await client.get("/api/products")).json()["items"][0]

    assert product["listed_days"] >= 1


async def test_price_drop_rate_only_in_deals(client, session):
    """
    일반 목록에서는 인하율을 계산하지 않는다. 매물마다 이력을 조회하면 N+1이 된다.
    인하 정보가 필요한 화면은 /api/products/deals 를 쓴다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", price=4_000_000)])
    await repository.upsert_items([make_item("https://ex.com/1", price=3_000_000)])

    listed = (await client.get("/api/products")).json()["items"][0]
    assert listed["price_drop_rate"] is None

    deals = (await client.get("/api/products/deals")).json()
    assert deals["count"] == 1
    assert deals["items"][0]["price_drop_rate"] == 25.0


async def test_tags_contain_brand_and_source(client, session):
    await repository.upsert_items(
        [make_item("https://ex.com/1", title="샤넬 클래식 플랩")]
    )

    product = (await client.get("/api/products")).json()["items"][0]

    assert "샤넬" in product["tags"]
    assert "중고나라" in product["tags"]
    assert "클래식" in product["tags"]


# ---------------------------------------------------------------------------
# 필터와 목록
# ---------------------------------------------------------------------------


async def test_shares_filters_with_crawled_items(client, session):
    """
    두 엔드포인트가 다른 조건을 보면 "목록에는 있는데 상품에는 없는" 상황이 생긴다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/1", price=1_000_000),
            make_item("https://ex.com/2", price=9_000_000),
        ]
    )

    params = {"max_price": 2_000_000}
    products = (await client.get("/api/products", params=params)).json()
    items = (await client.get("/api/crawled-items", params=params)).json()

    assert products["total"] == items["total"] == 1


async def test_sold_items_hidden_by_default(client, session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/1"),
            make_item("https://ex.com/2", is_sold=True),
        ]
    )

    body = (await client.get("/api/products")).json()

    assert body["total"] == 1
    assert body["items"][0]["platform_prices"][0]["in_stock"] is True


async def test_pagination(client, session):
    await repository.upsert_items(
        [make_item(f"https://ex.com/{i}") for i in range(5)]
    )

    body = (await client.get("/api/products", params={"limit": 2})).json()

    assert body["total"] == 5
    assert body["count"] == 2
    assert body["has_next"] is True


# ---------------------------------------------------------------------------
# 단건 조회
# ---------------------------------------------------------------------------


async def test_get_single_product(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    product_id = (await client.get("/api/products")).json()["items"][0]["id"]

    body = (await client.get(f"/api/products/{product_id}")).json()

    assert body["id"] == product_id
    assert body["brand"] == "샤넬"


async def test_unknown_id_prefix_is_404(client, session):
    """
    나중에 모델 그룹 id("model-샤넬-클래식")가 생기면 종류를 구분해야 한다.
    접두어 검사가 그 자리를 미리 잡아 둔다.
    """
    assert (await client.get("/api/products/model-샤넬-클래식")).status_code == 404
    assert (await client.get("/api/products/123")).status_code == 404


async def test_missing_product_is_404(client, session):
    assert (await client.get("/api/products/item-999999")).status_code == 404