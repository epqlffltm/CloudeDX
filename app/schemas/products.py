# app/schemas/products.py

"""
프론트엔드(ReLuxe)가 소비하는 상품 응답.

프론트는 **상품 단위**로 설계됐다. 하나의 상품에 여러 플랫폼 가격이 붙는 구조다.
우리 DB는 **매물 단위**다 — 게시글 하나가 한 행이다. 이 간극을 여기서 메운다.

지금은 매물 하나를 상품 하나로 내려준다. `platform_prices`의 원소가 항상 1개다.
프론트의 mock 데이터도 실제로 그렇게 되어 있었다 — 62개 상품 중 57개가 플랫폼
하나짜리였다. 겉모습만 상품이고 실제로는 매물이었던 셈이다.

진짜 그룹화(같은 모델의 여러 매물을 한 상품으로 묶기)는 모델 추출률이 올라간 뒤에
한다. 현재 37%라서, 지금 묶으면 나머지 63%가 "모델 불명" 한 덩어리로 몰려 의미가 없다.

**프론트 타입에서 뺀 것들이 있다.** 팀과 합의한 내용이다.

| 필드 | 왜 뺐나 |
|---|---|
| `views`, `likes` | 사이트가 카드에 주지 않는다. 지어내면 거짓말이다 |
| `popularity_rank` | 조회수가 없으니 산출할 근거가 없다 |
| `grade` (S/A+/A/B) | 제목의 "정품S급"은 셀러 자칭이다. 등급으로 보여주면 우리가 검증한 것처럼 오해된다 |
| `retail_price` | 정가 데이터가 없다 |

대신 **우리만 있는 데이터**를 넣었다. 가격 이력에서 나오는 값들이고, 경쟁 서비스의
단순 목록에는 없다.

    listed_days      며칠째 안 팔리고 있는가
    price_drop_rate  최근 얼마나 값을 내렸는가
    posted_at        언제 올라왔는가
"""

from datetime import datetime

from pydantic import BaseModel, Field


class PlatformPrice(BaseModel):
    """한 플랫폼에서의 가격. 프론트의 PlatformPrice에 대응한다."""

    platform_name: str = Field(description="수집처 ('당근마켓' / '중고나라')")
    price: int | None = Field(
        default=None,
        description="가격(원). 파싱하지 못했으면 null이고, 그때 화면은 '가격 미상'으로 둔다",
    )
    in_stock: bool = Field(description="아직 구매 가능한지 (판매완료·삭제면 false)")
    link_url: str = Field(description="원글 주소")
    seller_type: str | None = Field(
        default=None,
        description=(
            "'certified'(사이트 인증 셀러) 또는 'individual'. null은 '개인 판매자'가 "
            "아니라 **판정할 수 없음**을 뜻한다 — 당근마켓에는 인증 배지 체계가 없다"
        ),
    )


class ProductOut(BaseModel):
    """
    프론트가 카드 하나로 그리는 단위.

    id가 문자열인 이유는 나중에 진짜 그룹화를 도입할 때 `"item-123"`과
    `"model-샤넬-클래식"`을 함께 담아야 하기 때문이다. 지금부터 문자열로 두면
    그때 프론트를 고치지 않아도 된다.
    """

    id: str = Field(description="상품 식별자. 현재는 'item-{매물id}' 형태")
    category: str = Field(default="bag", description="현재는 가방만 수집한다")
    brand: str
    model_name: str | None = Field(
        default=None,
        description=(
            "추출한 모델명. **제목에서 특정하지 못하면 null이다**(현재 63%). "
            "채워 넣지 않는 이유는 나중에 진짜 모델 그룹화를 할 때 "
            "가짜 모델명이 섞이면 그룹이 어긋나기 때문이다"
        ),
    )
    korean_name: str = Field(description="화면에 보여줄 제목. 검색용 브랜드 나열 꼬리를 뗀 것")
    thumbnail_url: str | None = None

    lowest_price: int | None = Field(
        default=None, description="이 상품의 최저가(원). 매물이 하나면 그 가격이다"
    )
    platform_prices: list[PlatformPrice] = Field(
        description="플랫폼별 가격. 현재는 항상 1개이고, 모델 그룹화 후 여러 개가 된다"
    )

    tags: list[str] = Field(
        default_factory=list, description="브랜드·모델·수집처로 만든 검색 보조 태그"
    )

    # ---- 우리만 있는 데이터 ----

    posted_at: datetime | None = Field(
        default=None,
        description="원글 등록 시각. 사이트가 표기하지 않으면 null",
    )
    listed_days: int = Field(
        description=(
            "우리가 이 매물을 관측한 일수. 오래 안 팔린 매물은 값을 깎을 여지가 "
            "있다는 신호다"
        )
    )
    price_drop_rate: float | None = Field(
        default=None,
        description=(
            "첫 관측 가격 대비 현재 인하율(%). 값을 내렸다는 건 파는 쪽이 급해졌다는 "
            "신호다. 가격이 그대로거나 올랐으면 null"
        ),
    )


class ProductListResponse(BaseModel):
    total: int
    count: int
    limit: int
    offset: int
    has_next: bool
    items: list[ProductOut]