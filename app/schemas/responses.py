# app/schemas/responses.py

"""
JSON API 응답에 쓰이는 Pydantic 모델.

HTML 게시판은 ORM 객체를 템플릿에 바로 넘기므로 이 모델을 거치지 않는다. 여기 있는
모델들은 나중에 붙을 프론트엔드가 실제로 소비할 계약(contract)이라, 필드를 지우거나
이름을 바꾸면 프론트가 깨진다는 전제로 다룬다.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PagedResponse(BaseModel):
    """
    목록 응답의 공통 껍데기.

    has_next를 서버가 직접 내려주는 이유: 클라이언트가 offset + count < total을
    매번 계산하게 하면 그 규칙이 프론트 코드에 복사되고, 나중에 커서 기반
    페이지네이션으로 바꿀 때 양쪽을 같이 고쳐야 한다.
    """

    total: int = Field(description="필터 조건에 맞는 전체 건수")
    count: int = Field(description="이번 응답에 포함된 건수")
    limit: int = Field(description="요청한 페이지당 개수")
    offset: int = Field(description="요청한 시작 위치")
    has_next: bool = Field(description="다음 페이지가 있는지")


class CrawledItemOut(BaseModel):
    """매물 한 건."""

    # ItemRecord(SQLAlchemy ORM 객체)를 그대로 넣어도 속성을 읽어 직렬화할 수 있게 한다.
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="영구 식별자. 크롤링이 다시 돌아도 바뀌지 않는다")
    source: str = Field(description="수집처 ('당근마켓' / '중고나라')")
    brand: str
    title: str
    price: str | None = Field(default=None, description="원문 가격 문자열 (예: '4,000,000원')")
    price_value: int | None = Field(
        default=None,
        description="숫자로 파싱한 가격(원). 파싱에 실패하면 null이고, 가격 필터에서도 제외된다",
    )
    region: str | None = None
    time_text: str | None = Field(
        default=None,
        description="사이트 원문 시간 표기 (예: '3시간 전', '끌올 2일 전')",
    )
    posted_at: datetime | None = Field(
        default=None,
        description=(
            "원글 등록 시각. time_text를 수집 시점 기준으로 환산한 값이라 시간 단위의 "
            "오차가 있고, 사이트가 표기하지 않으면 null이다. null일 때 화면에서는 "
            "first_seen_at으로 대체하되 '등록'이 아니라 '수집'으로 표기한다"
        ),
    )
    image_url: str | None = None
    url: str = Field(description="원글 링크. 이 값이 upsert의 유니크 키이기도 하다")
    is_sold: bool
    first_seen_at: datetime = Field(description="이 매물을 처음 수집한 시각 (갱신되지 않음)")
    last_seen_at: datetime = Field(description="마지막으로 다시 확인한 시각")


class CrawledItemListResponse(PagedResponse):
    items: list[CrawledItemOut]


class MetaResponse(BaseModel):
    """
    필터 UI를 그리는 데 필요한 값들.

    브랜드/수집처 목록을 프론트에 하드코딩하면 app/crawler/brands.py를 고칠 때마다
    양쪽을 같이 고쳐야 한다. 서버가 내려주면 브랜드를 추가해도 프론트는 그대로 둔다.
    """

    sources: list[str] = Field(description="수집처 목록. source 필터에 그대로 넣을 수 있다")
    brands: list[str] = Field(description="브랜드 목록. brand 필터에 그대로 넣을 수 있다")
    total_items: int = Field(description="현재 DB에 저장된 전체 매물 수")
    last_crawled_at: datetime | None = Field(
        default=None,
        description="마지막 수집 시각. 데이터가 한 건도 없으면 null",
    )
