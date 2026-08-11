# app/schemas/responses.py

"""
API 응답에 쓰이는 Pydantic 모델.

DB(items 테이블, app.db.models.ItemRecord)를 그대로 반영한다. HTML 게시판은
ORM 객체를 템플릿에 바로 넘기므로 이 모델을 거치지 않고, JSON API만 사용한다.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PagedResponse(BaseModel):
    """
    목록 응답의 공통 껍데기.

    total은 필터 조건에 맞는 전체 건수, count는 이번 응답에 실제로 담긴 건수다.
    다음 페이지 존재 여부는 offset + count < total 로 판단한다.
    """

    total: int = Field(description="필터 조건에 맞는 전체 건수")
    count: int = Field(description="이번 응답에 포함된 건수")
    limit: int = Field(description="요청한 페이지당 개수")
    offset: int = Field(description="요청한 시작 위치")


class CrawledItemOut(BaseModel):
    """DB에 저장된 매물 한 건."""

    # ItemRecord(SQLAlchemy ORM 객체)를 그대로 넣어도 속성을 읽어 직렬화할 수 있게 한다.
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="DB PK. 크롤링이 다시 돌아도 바뀌지 않는 영구 식별자")
    source: str = Field(description="수집처 ('당근마켓' / '중고나라')")
    brand: str
    title: str
    price: str | None = Field(default=None, description="원문 가격 문자열 (예: '4,000,000원')")
    price_value: int | None = Field(default=None, description="숫자로 파싱한 가격. 파싱 실패 시 null")
    region: str | None = None
    time_text: str | None = Field(default=None, description="원문 시간 표기 (예: '3시간 전')")
    image_url: str | None = None
    url: str = Field(description="매물 원본 링크. 이 값이 upsert의 유니크 키다")
    is_sold: bool
    first_seen_at: datetime = Field(description="이 매물을 처음 수집한 시각 (갱신되지 않음)")
    last_seen_at: datetime = Field(description="마지막으로 다시 확인한 시각")


class CrawledItemListResponse(PagedResponse):
    items: list[CrawledItemOut]
