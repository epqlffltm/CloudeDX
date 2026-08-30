# app/schemas/requests.py

"""
API 요청(쿼리 파라미터)에 쓰이는 Pydantic 모델.

라우터 함수 시그니처에 Query 파라미터를 하나씩 나열하면 필터가 늘어날수록 시그니처가
길어지고, 같은 검증 규칙(limit 범위 등)이 엔드포인트마다 복사된다. 그래서 필터 묶음을
모델 하나로 만들어 Annotated[..., Query()]로 주입한다 (FastAPI 0.115+ 지원).

/api/crawled-items와 /api/products가 같은 모델을 공유한다. 두 경로의 필터 조건이
갈라지지 않게 하려는 것이고, 조건이 어긋나면 "API로는 나오는데 화면에는 안 나오는"
상황이 생긴다.

검증도 여기서 끝낸다 — min_price > max_price 같은 모순은 repository까지 내려가기 전에
422로 걸러진다.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PaginationParams(BaseModel):
    """목록 조회 공통 페이지네이션."""

    limit: int = Field(default=20, ge=1, le=100, description="페이지당 개수 (1~100)")
    offset: int = Field(default=0, ge=0, description="건너뛸 개수 (시작 위치)")


class CrawledItemFilterParams(PaginationParams):
    """매물 목록 필터. /api/crawled-items와 /api/products가 공유한다."""

    source: str | None = Field(
        default=None,
        description="수집처. '당근마켓'(동네 시세) 또는 '중고나라'(전국 최저가)",
        examples=["중고나라"],
    )
    brand: str | None = Field(
        default=None,
        description="브랜드. '구찌' / '에르메스' / '샤넬' / '루이비통'",
        examples=["샤넬"],
    )
    search: str | None = Field(
        default=None,
        description="제목 부분 일치 검색어 (대소문자 무시)",
    )
    is_sold: bool | None = Field(
        default=None,
        description="판매완료 여부. 지정하지 않으면 활성 매물 기준으로 전부 포함",
    )
    authenticated_only: bool = Field(
        default=False,
        description=(
            "정품 인증 매물만 볼지. 기업고객이 증표를 확인해 등록한 매물만 남는다. "
            "기본은 false로 전체를 본다 — 인증분은 아직 수가 적어서, 기본값으로 "
            "켜면 목록이 거의 비어 보인다"
        ),
    )
    include_unusable: bool = Field(
        default=False,
        description=(
            "정제에서 걸러진 매물(가방 아님·대상 외 브랜드)까지 포함할지. 기본은 "
            "제외한다 — 향수나 쇼핑백이 가방 목록에 섞인다. "
            "정제 규칙을 점검할 때만 true로 둔다"
        ),
    )
    category: Literal["bag", "watch", "jewelry", "apparel", "shoes", "unknown"] | None = Field(
        default=None,
        description=(
            "카테고리. bag/watch/jewelry/apparel/shoes 중 하나. 지정하지 않으면 전체. "
            "'unknown'은 분류 실패분으로, 정제 규칙을 점검할 때만 쓴다"
        ),
    )
    order_by: Literal["latest", "oldest", "price_asc", "price_desc"] = Field(
        default="latest",
        description=(
            "정렬. latest(최신순, 기본) / oldest(오래된순) / "
            "price_asc(낮은 가격순) / price_desc(높은 가격순). "
            "가격 정렬에서 price_value가 NULL인 매물(가격 미상)은 방향과 무관하게 "
            "항상 맨 뒤다 — 가격을 물어본 정렬에서 가격 없는 행이 먼저 나오면 안 된다. "
            "Literal이라 목록 밖의 값은 422로 걸러진다"
        ),
    )
    include_inactive: bool = Field(
        default=False,
        description=(
            "비활성 매물(판매완료·연속 미발견)까지 포함할지. 기본은 제외한다 — "
            "이미 사라진 매물이 목록에 남으면 클릭이 죽은 링크로 이어진다. "
            "정제 규칙 점검처럼 전체 데이터가 필요한 경우에만 true로 둔다"
        ),
    )
    min_price: int | None = Field(default=None, ge=0, description="최소 가격 (원)")
    max_price: int | None = Field(default=None, ge=0, description="최대 가격 (원)")

    @model_validator(mode="after")
    def check_price_range(self):
        """
        min > max면 조건상 결과가 항상 0건이다. 빈 목록을 주는 것보다 요청이 잘못됐다고
        알려주는 편이 디버깅에 낫다 (FastAPI가 이 ValueError를 422로 변환한다).
        """
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price는 max_price보다 클 수 없습니다.")

        return self