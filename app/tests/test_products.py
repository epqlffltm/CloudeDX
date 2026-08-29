# app/tests/test_products.py

"""
프론트엔드용 매물 API 테스트.

이 계층은 **우리 도메인(운영 필드 전부)과 프론트 계약(화면 최소 필드) 사이의
경계**다. 예전에는 매물을 '상품'으로 포장하는 어댑터였지만, 그룹핑을 포기하면서
포장을 걷어냈다 — 이제 지키려는 것은 세 가지다.

1. **없는 데이터를 지어내지 않는다.** 가격을 파싱하지 못했으면 null이다.
   views·grade처럼 사이트가 주지 않는 값은 계약에 아예 없다.
2. **계약이 최소로 유지된다.** reject_reason·missing_count 같은 운영 필드가
   화면 계약으로 새면 프론트가 그걸 그리기 시작하고, 그때부터 운영 컬럼을
   못 바꾸게 된다.
3. **두 엔드포인트가 같은 데이터를 본다.** /api/products와 /api/crawled-items가
   다른 조건을 쓰면 "목록에는 있는데 화면에는 없는" 상황이 생긴다.
"""

from app.db import repository
from app.domain.models import CrawledItem


def make_item(
    url: str,
    *,
    price: int | None = 4_000_000,
    title: str = "샤넬 클래식 플랩 캐비어",
    source: str = "중고나라",
    is_sold: bool = False,
    time_text: str = "3시간 전",
):
    return CrawledItem(
        source=source,
        brand="샤넬",
        title=title,
        price=f"{price:,}원" if price else None,
        price_value=price,
        region="서초구",
        time_text=time_text,
        image_url="https://img.example.com/1.jpg",
        url=url,
        is_sold=is_sold,
        seller_type=None,
    )


async def test_maps_item_to_listing(client, session):
    """계약 필드 전체가 컬럼 그대로 실려 나온다. 파생값이 없어야 한다."""
    await repository.upsert_items([make_item("https://ex.com/1")])

    body = (await client.get("/api/products")).json()
    listing = body["items"][0]
    assert set(listing) == {
        "id",
        "source",
        "title",
        "brand",
        "category",
        "price",
        "image_url",
        "item_url",
        "seller_id",
        "is_authenticated",
    }
    assert isinstance(listing["id"], int)
    assert listing["source"] == "중고나라"
    assert listing["brand"] == "샤넬"
    assert listing["price"] == 4_000_000
    assert listing["image_url"] == "https://img.example.com/1.jpg"
    assert listing["item_url"] == "https://ex.com/1"


async def test_category_defaults_to_bag(client, session):
    """
    크롤러는 category를 모른다. DB 기본값('bag')이 채우는지 확인한다.
    두 번째 카테고리를 열 때 이 테스트가 계약의 출발점이 된다.
    """
    await repository.upsert_items([make_item("https://ex.com/1")])

    listing = (await client.get("/api/products")).json()["items"][0]

    assert listing["category"] == "bag"


async def test_title_is_clean_title(client, session):
    """화면 제목에는 검색용 브랜드 나열 꼬리가 없어야 한다."""
    title = "샤넬 클래식 캐비어 클러치백 정품S급(감정O)구찌프라다루이비통디올고야드샤넬셀린느"
    await repository.upsert_items([make_item("https://ex.com/1", title=title)])

    listing = (await client.get("/api/products")).json()["items"][0]

    assert "프라다" not in listing["title"]
    assert listing["title"].startswith("샤넬 클래식")


async def test_price_null_when_unparsed(client, session):
    """
    가격을 파싱하지 못한 매물은 null로 내려가되 목록에서 빠지지 않는다.
    0으로 채우면 최저가 정렬에서 "0원짜리 샤넬"이 맨 위로 올라온다.
    """
    await repository.upsert_items([make_item("https://ex.com/1", price=None)])

    body = (await client.get("/api/products")).json()

    assert body["total"] == 1
    assert body["items"][0]["price"] is None


async def test_unusable_items_hidden_by_default(client, session):
    """
    정제에서 걸러진 매물(가방 아님)은 기본 노출에서 빠진다. "샤넬 가방" 목록에
    향수가 섞이면 탐색이 오염된다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/1"),
            make_item("https://ex.com/2", title="샤넬 넘버5 향수 미개봉"),
        ]
    )

    body = (await client.get("/api/products")).json()

    assert body["total"] == 1
    assert body["items"][0]["item_url"] == "https://ex.com/1"


async def test_sold_items_hidden_by_default(client, session):
    await repository.upsert_items(
        [
            make_item("https://ex.com/1"),
            make_item("https://ex.com/2", is_sold=True),
        ]
    )

    body = (await client.get("/api/products")).json()

    assert body["total"] == 1


# ---------------------------------------------------------------------------
# 필터와 목록
# ---------------------------------------------------------------------------


async def test_shares_filters_with_crawled_items(client, session):
    """
    두 엔드포인트가 다른 조건을 보면 "목록에는 있는데 화면에는 없는" 상황이 생긴다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/1", price=1_000_000),
            make_item("https://ex.com/2", price=9_000_000),
        ]
    )

    params = {"max_price": 2_000_000}
    listings = (await client.get("/api/products", params=params)).json()
    items = (await client.get("/api/crawled-items", params=params)).json()

    assert listings["total"] == items["total"] == 1


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


async def test_get_single_listing(client, session):
    await repository.upsert_items([make_item("https://ex.com/1")])
    listing_id = (await client.get("/api/products")).json()["items"][0]["id"]

    body = (await client.get(f"/api/products/{listing_id}")).json()

    assert body["id"] == listing_id
    assert body["brand"] == "샤넬"


async def test_missing_listing_is_404(client, session):
    assert (await client.get("/api/products/999999")).status_code == 404


async def test_non_numeric_id_is_422(client, session):
    """
    id는 정수 PK다. 예전 "item-{숫자}" 형식은 모델 그룹 id와 구분하려던 자리였는데,
    그룹핑을 포기하면서 존재 이유가 사라졌다. 형식이 틀리면 404가 아니라 422다 —
    "없는 매물"과 "잘못된 요청"은 다른 문제다.
    """
    assert (await client.get("/api/products/item-1")).status_code == 422


# ---------------------------------------------------------------------------
# 정렬 (order_by)
#
# 정렬은 서버가 한다. 클라이언트가 받아온 한 페이지만 재정렬하면 "전체에서 가장
# 싼 매물"이 아니라 "이 페이지에서 가장 싼 매물"이 되고, 화면은 그 차이를 숨긴다.
# ---------------------------------------------------------------------------


async def test_order_price_asc_puts_nulls_last(client, session):
    """낮은 가격순. 가격 미상(NULL)은 방향과 무관하게 항상 맨 뒤다."""
    await repository.upsert_items(
        [
            make_item("https://ex.com/1", price=3_000_000),
            make_item("https://ex.com/2", price=1_000_000),
            make_item("https://ex.com/3", price=None),
        ]
    )

    items = (await client.get("/api/products?order_by=price_asc")).json()["items"]

    assert [it["price"] for it in items] == [1_000_000, 3_000_000, None]


async def test_order_price_desc_puts_nulls_last(client, session):
    """높은 가격순에서도 NULL이 먼저 나오면 안 된다 — DESC의 기본 NULL 위치는 맨 앞이다."""
    await repository.upsert_items(
        [
            make_item("https://ex.com/1", price=3_000_000),
            make_item("https://ex.com/2", price=1_000_000),
            make_item("https://ex.com/3", price=None),
        ]
    )

    items = (await client.get("/api/products?order_by=price_desc")).json()["items"]

    assert [it["price"] for it in items] == [3_000_000, 1_000_000, None]


async def test_order_latest_and_oldest_are_reverses(client, session):
    """최신순과 오래된순은 같은 기준(coalesce(posted_at, first_seen_at))의 역방향이다."""
    await repository.upsert_items(
        [
            make_item("https://ex.com/old", title="샤넬 클래식 플랩 옛 매물", time_text="10시간 전"),
            make_item("https://ex.com/new", title="샤넬 클래식 플랩 새 매물", time_text="1시간 전"),
        ]
    )

    latest = (await client.get("/api/products")).json()["items"]
    oldest = (await client.get("/api/products?order_by=oldest")).json()["items"]

    assert latest[0]["title"] == "샤넬 클래식 플랩 새 매물"
    assert oldest[0]["title"] == "샤넬 클래식 플랩 옛 매물"
    assert [it["id"] for it in oldest] == [it["id"] for it in reversed(latest)]


async def test_order_same_price_is_stable_across_pages(client, session):
    """
    같은 가격이 흔하다(정찰가 리셀). id 2차 정렬이 없으면 페이지를 넘길 때
    같은 매물이 두 번 보이거나 건너뛰어진다 — limit=1로 두 페이지를 떠서
    합집합이 정확히 전체와 일치하는지 본다.
    """
    await repository.upsert_items(
        [
            make_item("https://ex.com/1", price=2_000_000),
            make_item("https://ex.com/2", price=2_000_000),
        ]
    )

    page1 = (await client.get("/api/products?order_by=price_asc&limit=1&offset=0")).json()
    page2 = (await client.get("/api/products?order_by=price_asc&limit=1&offset=1")).json()
    ids = {page1["items"][0]["id"], page2["items"][0]["id"]}

    assert len(ids) == 2


async def test_unknown_order_by_is_422(client, session):
    """Literal 화이트리스트 밖의 값은 SQL 근처에도 못 가고 422로 끝난다."""
    assert (await client.get("/api/products?order_by=id;drop")).status_code == 422


# ---------------------------------------------------------------------------
# 카테고리
#
# 분류(cleaning)→저장(upsert)→필터(API)→집계(meta)가 한 축으로 이어지는지 본다.
# 분류 규칙 자체는 test_cleaning이 맡고, 여기서는 배선을 검증한다.
# ---------------------------------------------------------------------------


def make_typed(url: str, title: str, brand: str, source: str = "중고나라"):
    """카테고리 테스트용 — 브랜드와 제목을 자유롭게 주는 make_item 변형."""
    return CrawledItem(
        source=source, brand=brand, title=title,
        price="1,000,000원", price_value=1_000_000,
        region=None, time_text="3시간 전",
        image_url="https://img.example.com/1.jpg", url=url,
        is_sold=False, seller_type=None,
    )


async def test_category_flows_from_classification_to_api(client, session):
    """시계·주얼리도 이제 노출 대상이고, category 필터로 갈라진다."""
    await repository.upsert_items(
        [
            make_typed("https://ex.com/b1", "샤넬 클래식 플랩 미디움", "샤넬"),
            make_typed("https://ex.com/w1", "롤렉스 서브마리너 시계 풀셋", "롤렉스"),
            make_typed("https://ex.com/j1", "까르띠에 러브 팔찌 로즈골드", "까르띠에"),
        ]
    )

    bags = (await client.get("/api/products?category=bag")).json()
    watches = (await client.get("/api/products?category=watch")).json()
    all_items = (await client.get("/api/products")).json()

    assert bags["total"] == 1 and bags["items"][0]["category"] == "bag"
    assert watches["total"] == 1 and watches["items"][0]["brand"] == "롤렉스"
    assert all_items["total"] == 3, "category 미지정은 전체"


async def test_meta_counts_by_category(client, session):
    await repository.upsert_items(
        [
            make_typed("https://ex.com/b1", "샤넬 클래식 플랩 미디움", "샤넬"),
            make_typed("https://ex.com/b2", "디올 레이디디올 미디엄", "디올"),
            make_typed("https://ex.com/s1", "구찌 에이스 스니커즈 265", "구찌"),
        ]
    )

    categories = (await client.get("/api/meta")).json()["categories"]

    assert categories["bag"] == 2
    assert categories["shoes"] == 1
    assert categories["watch"] == 0, "수집 전 카테고리도 0으로 키가 존재해야 한다"


async def test_unknown_category_is_hidden_but_queryable(client, session):
    """분류 실패분은 'unknown'으로 저장되고, 기본 노출에서는 정제 단계에서 빠진다."""
    await repository.upsert_items(
        [make_typed("https://ex.com/u1", "샤넬 뭔지 모를 물건", "샤넬")]
    )

    default = (await client.get("/api/products")).json()
    debug = (
        await client.get("/api/crawled-items?category=unknown&include_unusable=true")
    ).json()

    assert default["total"] == 0
    assert debug["total"] == 1


async def test_invalid_category_is_422(client, session):
    assert (await client.get("/api/products?category=furniture")).status_code == 422
