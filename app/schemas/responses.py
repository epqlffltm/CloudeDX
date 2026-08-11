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


class CrawlerStatus(BaseModel):
    """
    백그라운드 수집기의 현재 상태.

    서버는 크롤링을 기다리지 않고 바로 열리기 때문에, 방금 뜬 서버는 목록이 비어 있다.
    그게 "매물이 없다"인지 "아직 수집 중"인지 클라이언트가 구분할 수 있어야 한다.
    """

    is_running: bool = Field(description="지금 수집이 진행 중인지")
    started_at: datetime | None = Field(
        default=None, description="현재(또는 마지막) 라운드가 시작된 시각"
    )
    last_finished_at: datetime | None = Field(
        default=None, description="마지막 라운드가 끝난 시각. 성공/실패 모두 기록된다"
    )
    last_item_count: int | None = Field(
        default=None, description="마지막으로 성공한 라운드에서 저장한 건수"
    )
    last_error: str | None = Field(
        default=None,
        description="마지막 라운드가 실패했다면 그 이유. 성공하면 null로 초기화된다",
    )
    rounds_completed: int = Field(
        description="성공한 라운드 수. 0이면 아직 한 번도 성공하지 못했다는 뜻"
    )
    interval_minutes: int = Field(description="수집 주기(분)")


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
        description="DB 기준 마지막 수집 시각. 데이터가 한 건도 없으면 null",
    )
    crawler: CrawlerStatus = Field(description="백그라운드 수집기의 현재 상태")


class DatabaseCheck(BaseModel):
    """/ready의 DB 연결 확인 결과."""

    connected: bool = Field(description="DB에 쿼리를 보낼 수 있는지")
    error: str | None = Field(
        default=None,
        description=(
            "연결에 실패했다면 예외 타입 이름. 예외 메시지에는 접속 정보가 섞여 나올 수 "
            "있어서 타입만 노출한다"
        ),
    )


class MigrationCheck(BaseModel):
    """/ready의 스키마 버전 확인 결과."""

    current: str | None = Field(
        default=None,
        description="DB에 실제로 적용된 리비전. 마이그레이션을 한 번도 안 돌렸으면 null",
    )
    head: str | None = Field(
        default=None,
        description="코드가 기대하는 최신 리비전. head가 여럿이면 null이고 heads를 본다",
    )
    heads: list[str] = Field(
        description="코드가 기대하는 최신 리비전 목록. 브랜치가 갈리면 둘 이상이 된다"
    )
    up_to_date: bool = Field(description="DB 스키마가 코드가 기대하는 버전인지")


class ReadyResponse(BaseModel):
    """
    /ready 응답.

    준비되지 않았을 때도 본문은 그대로 내려간다(상태 코드만 503). 무엇 때문에
    실패했는지 알아야 조치할 수 있기 때문이다.
    """

    ready: bool = Field(description="트래픽을 받아도 되는 상태인지")
    database: DatabaseCheck
    migration: MigrationCheck