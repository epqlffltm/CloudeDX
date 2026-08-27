# app/schemas/products.py

"""
프론트엔드(ReLuxe)가 소비하는 매물 응답.

예전에는 매물을 '상품' 모양으로 포장해서 내려줬다 — 하나의 상품에 플랫폼별 가격이
붙는 다나와식 구조다. 그 포장을 걷어냈다. 데이터가 그 구조를 지지한 적이 없어서다.

- `platform_prices`는 항상 원소 1개였다. 여러 개가 되려면 같은 모델의 매물을 묶어야
  하는데, 모델 추출률이 37%라 묶는 순간 나머지 63%가 "모델 불명" 한 덩어리로 몰린다.
- `lowest_price`는 매물이 하나이므로 그냥 그 매물의 가격이었다. 이름만 최저가였다.
- 수집처가 늘면서 등록 시각을 표기하지 않는 사이트, 가격 수정이 불가능해 내리려면
  삭제 후 재등록해야 하는 사이트가 섞였다. 그 코퍼스에서 `listed_days`와
  `price_drop_rate`는 결측을 넘어 역선택이 된다 — 값을 내린 매물일수록 재등록되어
  "방금 올라온 정가 매물"로 보인다. 그래서 개별 매물 가격 이력 자체를 걷어냈다.

지금 계약은 매물 한 건을 그대로 내려준다. 1점물 탐색 서비스의 원형(부동산 매물
목록)과 같은 구조다: 목록 + 필터 + 원문 아웃링크.

**계약에서 뺀 것들.** 팀과 합의한 내용이다.

| 필드 | 왜 뺐나 |
|---|---|
| `views`, `likes`, `grade`, `retail_price` | 사이트가 카드에 주지 않는 값. 지어내면 거짓말이다 |
| `model_name` | 추출률 37%. 그룹핑을 포기했으므로 노출할 이유도 사라졌다 |
| `platform_prices`, `lowest_price` | 매물 단위에서는 포장만 남은 껍데기였다 |
| `posted_at`, `listed_days` | 등록 시각을 안 주는 수집처가 있어 사이트 간 비교가 성립하지 않는다 |
| `price_drop_rate` | 가격 수정이 불가능한 수집처에서 신호가 반대로 뒤집힌다 |

**`is_authenticated`는 왜 넣었나.** 위 표와 반대 방향이라 짚어 둔다. 저것들은 "사이트가
주지 않는 값을 우리가 지어내는 것"이라 뺐다. 이쪽은 우리가 실제로 아는 사실이다 —
기업고객 계정으로 올라온 매물인지 아닌지는 업로드 경로가 확정하고, 그 계정은 사람이
직접 발급한 것이다. 근거 없는 값이 아니라 근거가 우리 안에 있는 값이라 계약에 넣었다.

운영·디버깅용 전체 필드가 필요하면 /api/crawled-items(CrawledItemOut)를 쓴다.
"""

from pydantic import BaseModel, Field


class ListingOut(BaseModel):
    """
    프론트가 카드 하나로 그리는 단위. 매물 한 건이다.

    계산해서 만드는 값이 없다 — 전부 items 테이블 컬럼을 고른 것이다. 파생값이
    필요해지면 여기서 지어내지 말고, 그 값이 전 수집처에서 성립하는지부터 따진다.
    posted_at·listed_days가 사라진 이유가 그것이다.
    """

    id: int = Field(description="매물 영구 식별자. 크롤링이 다시 돌아도 바뀌지 않는다")
    source: str = Field(
        description="수집처 ('당근마켓' / '중고나라'). 플랫폼 필터와 카드 뱃지에 쓴다"
    )
    title: str = Field(
        description=(
            "화면에 보여줄 제목. 검색용 브랜드 나열 꼬리를 뗀 정제 제목이고, 정제 전이면 "
            "원제목이다. 검색(search 파라미터)은 원제목을 대상으로 하므로, 검색어가 "
            "화면 제목에 안 보일 수 있다 — 의도된 비대칭이다"
        )
    )
    brand: str
    category: str = Field(description="상품 분류. 지금은 가방('bag')만 수집한다")
    price: int | None = Field(
        default=None,
        description="가격(원). 파싱하지 못했으면 null이고, 그때 화면은 '가격 미상'으로 둔다",
    )
    image_url: str | None = None
    item_url: str = Field(description="원문 매물 주소. 거래는 각 수집처에서 이루어진다")
    seller_id: int | None = Field(
        default=None,
        description=(
            "입점 판매자 id. 크롤링 매물은 null이다 — null은 '판매자를 모른다'가 "
            "아니라 '우리 판매자가 아니다'를 뜻한다. 값이 있으면 화면이 "
            "/api/sellers/{id}로 연락처와 매장 위치를 가져온다"
        ),
    )
    is_authenticated: bool = Field(
        default=False,
        description=(
            "정품 인증 뱃지. 기업고객이 증표를 확인해 등록한 매물에만 true다. "
            "크롤링분은 예외 없이 false — 원문 사이트의 매물을 검증한 적이 없다"
        ),
    )


class ListingListResponse(BaseModel):
    total: int
    count: int
    limit: int
    offset: int
    has_next: bool
    items: list[ListingOut]
