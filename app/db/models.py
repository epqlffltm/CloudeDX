# app/db/models.py

"""
SQLAlchemy ORM 모델.
- items      : 크롤링한 매물. url을 유니크 키로 써서 같은 매물은 갱신, 새 매물은 추가하는
               upsert 방식이다 (app/db/repository.py 참고).
- crawl_runs : 수집 라운드 기록. 크롤러와 백엔드가 별도 프로세스로 갈라져도 상태를
               공유하기 위한 것이다 (app/db/crawl_runs.py 참고).

스키마 변경은 Alembic으로 관리한다. 이 파일을 고친 뒤에는 반드시
    uv run alembic revision --autogenerate -m "설명"
    uv run alembic upgrade head
를 실행해야 실제 DB에 반영된다. 모델만 고치면 앱은 멀쩡히 뜨는데 쿼리에서 터진다.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 제약조건/인덱스 이름 규칙.
#
# 지정하지 않으면 DB가 알아서 이름을 붙이는데, 그 이름은 Alembic이 예측할 수 없다.
# 나중에 "이 유니크 제약을 삭제해라"는 마이그레이션을 자동 생성할 때 이름을 몰라서
# 실패하거나, 개발/운영 DB의 제약 이름이 서로 달라지는 문제가 생긴다.
# 규칙을 먼저 못 박아두면 어느 환경에서 만들어도 같은 이름이 나온다.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ItemRecord(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    brand: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 상품 분류 — bag / watch / jewelry / apparel / shoes, 판정 실패는 'unknown'.
    #
    # **검색 잡의 카테고리가 아니라 제목에서 다시 판정한 값이다**(upsert_items →
    # clean_title → classify_category). brand를 검색어가 아닌 제목으로 판정하는 것과
    # 같은 이유다 — "시계"로 검색해도 결과에 가방이 섞여 들어온다.
    #
    # server_default가 'bag'인 것은 이 컬럼이 생기기 전 행들 때문이고, 지금 들어오는
    # 행은 전부 판정값을 명시해서 넣는다.
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="bag", index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[str | None] = mapped_column(String(50))
    price_value: Mapped[int | None] = mapped_column(BigInteger, index=True)
    region: Mapped[str | None] = mapped_column(String(50))
    time_text: Mapped[str | None] = mapped_column(String(50))
    image_url: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 원글이 올라간 시각. time_text("3시간 전")를 수집 시점 기준으로 환산한 값이라
    # 시간 단위의 오차가 있고, 사이트가 표기를 안 하면 NULL이다. 그래서 nullable이며
    # 화면에서는 이 값이 없을 때 first_seen_at으로 대체한다.
    # 정렬/필터에 쓸 수 있게 인덱스를 건다.
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    # 판매자 유형. 중고나라의 인증셀러 배지에서 온다.
    # 당근마켓에는 대응 배지가 없어 항상 NULL이고, 그건 "개인 판매자"가 아니라
    # "판정할 수 없음"을 뜻한다 (app/domain/seller.py 참고).
    seller_type: Mapped[str | None] = mapped_column(String(20))

    # 이 매물을 등록한 입점 판매자. 크롤링분은 NULL이다.
    #
    # NULL이 "판매자를 모른다"가 아니라 "우리 판매자가 아니다"를 뜻한다. 크롤링
    # 매물에도 원문 사이트의 셀러가 있지만 그건 우리가 계약한 상대가 아니고,
    # 연락처를 화면에 띄울 근거도 없다. 그 구분을 컬럼 하나로 유지한다.
    #
    # ondelete는 SET NULL이다. 판매자를 지운다고 매물까지 사라지면, 이미 목록에
    # 노출되고 검색에 걸린 매물이 통째로 증발한다. 매물은 남기고 연결만 끊는다.
    seller_id: Mapped[int | None] = mapped_column(
        ForeignKey("sellers.id", ondelete="SET NULL"), index=True
    )

    # 정품 인증 뱃지. 화면 카드의 "정품인증" 씰이 이 값 하나만 본다.
    #
    # 크롤링분은 전부 False다. 원문 사이트의 매물을 우리가 검증한 적이 없고
    # 중개도 하지 않으므로, True로 두면 사실이 아닌 보증을 표시하게 된다.
    #
    # True가 되는 경로는 하나뿐이다 — source가 '직접등록'인 업로드 매물 중,
    # 업자가 CSV에 인증 표시를 한 행. 두 조건을 모두 요구하는 것은
    # repository._dedupe_by_url에서 강제한다.
    #
    # seller_type(중고나라 인증셀러 배지)과는 다른 축이다. 그쪽은 "사이트가
    # 인증한 셀러", 이쪽은 "우리가 계정을 발급한 업자가 증표를 확인한 물건"이다.
    # 한 컬럼에 합치면 두 가지 다른 보증이 같은 뱃지로 나간다.
    is_authenticated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", index=True
    )

    # ---- 정제 결과 --------------------------------------------------------
    #
    # brand는 크롤러의 검색어가 아니라 제목에서 다시 판정한 값이다. 실측 599건에서
    # "루이비통 가방"으로 검색한 218건 중 31건 이상이 실제로는 구찌였다 — 셀러가
    # 검색 노출을 위해 제목 끝에 브랜드를 20개씩 나열하기 때문이다.
    # 검색어는 search_brand에 그대로 남겨, 판정이 틀렸을 때 대조할 수 있게 한다.
    search_brand: Mapped[str | None] = mapped_column(String(20), index=True)

    # 스팸 꼬리를 뗀 제목. 화면 표시에 쓴다. 원본은 title에 남는다.
    clean_title: Mapped[str | None] = mapped_column(Text)

    # 목록에 노출할 수 있는 매물인지. 가방이 아니거나(향수·신발·쇼핑백) 대상 외
    # 브랜드면 False다. is_active와는 다른 축이다 — is_active는 "지금 살 수 있는가",
    # 이쪽은 "애초에 우리가 다루는 상품인가"를 뜻한다.
    is_usable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    # 제외 사유. 규칙을 조정할 때 무엇이 왜 걸렸는지 봐야 하므로 남긴다.
    reject_reason: Mapped[str | None] = mapped_column(String(60))

    # ---- 생명주기 --------------------------------------------------------
    #
    # 매물은 팔리거나 삭제되면 사이트에서 사라지는데, 크롤링 결과에 없다는 것만으로는
    # "사라졌다"고 단정할 수 없다. 수집 범위 밖으로 밀렸거나 일시적 오류일 수 있다.
    # 그래서 바로 지우지 않고 미발견 횟수를 세다가, 임계값을 넘으면 비활성 처리한다.

    # 화면에 기본 노출할지 여부. **데이터로서 유효한지가 아니다.**
    # 비활성 매물도 지우지 않는다. url이 유니크 키라서 행이 남아 있어야, 같은 매물이
    # 끌올로 재등장했을 때 새 매물로 중복 집계되지 않고 기존 행이 복구된다.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    # 연속으로 발견되지 않은 라운드 수. 다시 보이면 0으로 되돌린다.
    missing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # 비활성으로 바뀐 시각과 이유. 활성 상태면 둘 다 NULL.
    unavailable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 'sold'(판매완료 표기 확인) / 'missing'(연속 미발견). 둘의 신뢰도가 달라서 구분한다 —
    # sold는 사이트가 알려준 사실이고 missing은 우리 추정이다.
    unavailable_reason: Mapped[str | None] = mapped_column(String(20))

    # 이 매물을 처음/마지막으로 본 시점. url이 같으면 first_seen_at은 그대로 두고
    # last_seen_at만 갱신한다 (repository.py의 upsert 로직).
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- 인기 ------------------------------------------------------------
    #
    # 카드 클릭 누적 수. 대문 "인기 물품" 레일의 정렬 키다.
    #
    # 원천 기록은 item_click_events(한 세션이 한 매물을 30분에 한 번)이고, 이
    # 컬럼은 그 건수의 캐시다. 매 조회마다 이벤트 테이블을 COUNT하면 대문이
    # 열릴 때마다 집계가 돌기 때문에, 이벤트를 넣을 때 여기를 +1 해 둔다.
    # 두 값이 어긋나면 이벤트 테이블이 진실이다 — 이 컬럼은 다시 셀 수 있다.
    #
    # 화면 계약(ListingOut)에는 싣지 않는다. 클릭 수를 카드에 찍으면 "조회수"
    # 처럼 읽히는데, 그건 사이트가 주지 않아 계약에서 뺀 값이다. 정렬에만 쓴다.
    click_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", index=True
    )


class ItemClickEvent(Base):
    """
    매물 카드 클릭 한 건. 인기 집계의 원천이다.

    **한 세션이 한 매물을 30분 버킷에 한 번만** 남긴다 — (item_id, session_hash,
    bucket_start) 유니크가 그 규칙이다. 같은 카드를 연타하거나 새로고침해도 한
    번으로 센다. 큐·캐시 없이 DB 제약 하나로 중복을 거르는 것이 이 설계의
    전부라서, 나중에 앞단에 SQS·Redis SETNX를 붙여도 이 제약은 그대로 남아
    최종 방어선이 된다.

    session_hash는 익명 쿠키 값의 HMAC이다. 원값을 저장하지 않으므로 이 테이블만
    으로는 누가 눌렀는지 알 수 없다 — 인기 집계에 필요한 것은 "같은 사람인가"
    뿐이다.

    items가 지워지면 같이 지운다(CASCADE). 매물 없는 클릭 기록은 쓸 데가 없다.
    """

    __tablename__ = "item_click_events"
    __table_args__ = (
        UniqueConstraint("item_id", "session_hash", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # sha256 hex = 64자.
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # 클릭 시각을 30분 단위로 내림한 값 (app/domain/clicks.py bucket_start).
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LiveSearchRun(Base):
    """
    실시간 검색을 마지막으로 시도한 시각 — 검색어(정규형) 하나에 한 행.

    이 표 하나가 세 가지를 한꺼번에 막는다.

    1. **동시 호출**: 같은 검색어가 같은 순간에 여러 번 들어와도, 행을 갱신할 수
       있는 요청 하나만 통과한다. 나머지는 유니크 충돌로 대기했다가 갱신된 시각을
       기준으로 다시 판단해 걸린다.
    2. **연타·반복**: 쿨다운(LIVE_SEARCH_COOLDOWN_SECONDS) 동안 들어오는 순차
       요청도 같은 조건에 걸린다. 예전 어드바이저리 락은 이걸 못 막았다.
    3. **파드 여러 대**: 판단 근거가 DB 한 행이라 프로세스 메모리와 무관하다.

    키는 사용자가 친 원문이 아니라 `LiveQuery.search_key`(정규형)다. "루이뷔통 가방"과
    "루이비통 가방"이 같은 키로 접혀야 별칭마다 API를 따로 치지 않는다.
    `last_keyword`는 로그·디버그용으로 마지막 원문을 남기는 자리이고 판정에 쓰지 않는다.

    행은 검색어 수만큼만 늘고 지우지 않는다. 시연 규모에서 수백 행이라 정리 대상이
    아니다 — 오래된 행은 다음 요청이 그 자리에서 갱신한다.
    """

    __tablename__ = "live_search_runs"

    # 길이를 못 박는 이유가 있다. search_key 는 사용자 입력을 정규화만 한 문자열이라
    # 그대로 두면 입력 길이가 곧 인덱스 행 크기가 되는데, btree 인덱스 행에는 상한이
    # 있어서(약 2704바이트) 아주 긴 검색어에서 INSERT 자체가 실패한다.
    # app.domain.live_search.MAX_QUERY_LENGTH 가 입력 쪽에서 먼저 걸러내고,
    # 이 길이는 그보다 넉넉하게 잡은 두 번째 방어선이다.
    search_key: Mapped[str] = mapped_column(String(120), primary_key=True)

    # 실제로 번개장터에 보낸 마지막 검색어. 로그에서 "이 키가 무슨 검색어였나"를
    # 되짚기 위한 값이라 판정에는 쓰지 않는다.
    last_keyword: Mapped[str] = mapped_column(String(200), nullable=False)

    # 성공·실패와 무관하게 **시도한** 시각이다. 실패를 안 남기면 실패한 검색어만
    # 무한히 재시도할 수 있게 된다 — 상대 사이트가 막고 있을 때 가장 세게 두드리는
    # 셈이라, 실패야말로 기록해야 한다.
    last_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class UnavailableReason(StrEnum):
    """
    매물이 비활성이 된 이유.

    신뢰도가 다르다. SOLD는 사이트가 판매완료라고 표기한 것을 확인한 사실이고,
    MISSING은 "검색 결과에 계속 없다"는 우리 추정이다. 추정은 틀릴 수 있으므로
    (수집 범위 밖으로 밀렸거나, 차단당해 빈 결과를 받았거나) 다시 보이면 되살린다.
    """

    SOLD = "sold"
    MISSING = "missing"


class CrawlRunStatus(StrEnum):
    """
    수집 라운드의 상태.

    Postgres의 enum 타입 대신 문자열로 저장한다. enum 타입은 값을 추가할 때마다
    ALTER TYPE 마이그레이션이 필요하고 트랜잭션 안에서 다루기 까다로운데, 얻는 이점이
    이 규모에서는 없다.
    """

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class CrawlRun(Base):
    """
    수집 라운드 한 번의 기록.

    예전에는 이 상태를 프로세스 메모리(app/crawler/state.py)에 들고 있었다. 크롤러를
    별도 컨테이너로 분리하면서 그 방식이 깨졌다 — 백엔드 프로세스가 크롤러 프로세스의
    메모리를 볼 수 없으니 /api/meta가 항상 빈 상태를 내려주게 된다. DB에 남기면 두
    프로세스가 같은 곳을 보게 되고, 서버를 재시작해도 이력이 남는다.

    부수적으로 얻는 것이 둘 있다. 크롤러 프로세스가 두 개 뜨면 서로의 running 기록을
    보고 한쪽이 양보할 수 있고(scheduler._should_crawl_now), 수집이 언제부터 실패하기
    시작했는지 시간순으로 추적할 수 있다.
    """

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # running / success / failed. 최신 상태를 자주 조회하므로 인덱스를 건다.
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # 아직 도는 중이면 NULL이다.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 이 라운드에서 저장(upsert)한 건수. 실패하면 NULL.
    item_count: Mapped[int | None] = mapped_column(Integer)

    # 수집처·브랜드별 카드 파싱 성적.
    #
    #   {"당근마켓": {"루이비통": {"attempted": 61, "parsed": 4, "failed": 57,
    #                            "failure_rate": 0.934}}}
    #
    # 라운드 전체 수치 하나만 두지 않은 이유: 브랜드 하나만 깨졌을 때 전체로 합치면
    # 실패율이 희석된다. 당근 네 브랜드 중 루이비통만 5/50이어도 전체로는 22%라
    # 임계값에 안 걸리고, "당근은 살아 있는데 루이비통 파서만 깨졌다"를 알 수 없다.
    #
    # 별도 테이블 대신 JSONB로 둔 이유는 이 값을 조인하거나 집계할 일이 없어서다.
    # 라운드 하나를 볼 때 통째로 읽는 게 전부라면 컬럼 하나가 단순하다. 시계열
    # 분석이 필요해지면 그때 crawl_run_stats 테이블로 옮긴다.
    parse_health: Mapped[dict | None] = mapped_column(JSONB)

    # 실패 사유. 일부 사이트만 실패한 경우 status는 success지만 여기에 기록이 남는다.
    # 어떤 사이트가 왜 막혔는지가 나중에 셀렉터를 고칠 때 유일한 단서라 길이 제한을 두지 않는다.
    error: Mapped[str | None] = mapped_column(Text)

class Seller(Base):
    """
    입점 판매자.

    사이트를 갖고 있지 않은 사업자를 위한 자리다. 매장이 있는 판매자도, 온라인으로만
    파는 판매자도 상정한다 — has_store가 그 둘을 가른다.

    **계정 테이블이 아니다.** 로그인 계정은 설정에서 읽는 별도 체계이고(app/auth.py),
    여기는 화면에 표시할 사업자 정보다. 둘을 한 테이블로 합치면 계정 없이 정보만
    등록해 두는 경우(시연 시드가 그렇다)를 다룰 수 없다.

    **여기 담긴 값은 우리가 검증한 것이 아니다.** 사업자등록번호의 진위는 국세청
    API로만 확인할 수 있는데 백엔드가 폐쇄망에 있어 나가지 못한다. 저장하는 것은
    형식 검사를 통과한 값일 뿐이고, 화면 문구도 그 수준을 넘어서면 안 된다.
    """

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 사업자등록번호. 3-2-5 하이픈 형식으로 정규화해서 넣는다
    # (app/domain/sellers.py의 normalize_business_number).
    #
    # 유니크를 건다. 같은 사업자가 두 번 등록되면 매물이 두 판매자로 갈라져,
    # 화면에서 같은 가게가 서로 다른 연락처로 두 번 뜬다.
    business_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    phone: Mapped[str] = mapped_column(String(20), nullable=False)

    # 매장 보유 여부. False면 주소와 좌표가 없는 것이 정상이고, 화면은 지도를
    # 아예 그리지 않는다. "주소가 NULL이니 매장이 없나 보다"로 추정하지 않기 위해
    # 별도 컬럼으로 둔다 — 매장은 있는데 주소를 아직 안 적은 경우와 구분해야 한다.
    has_store: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    address: Mapped[str | None] = mapped_column(String(200))

    # 위경도. 폐쇄망이라 백엔드에서 지오코딩을 할 수 없어, 등록 시점에 이미 좌표가
    # 정해진 채로 들어온다(시드가 직접 넣거나, 브라우저가 지오코더를 호출해 폼에
    # 채워 보낸다). 클라이언트가 보내는 값이므로 저장 전에 한국 영토 범위를 검사한다.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # 판매자 소개. 상세 화면 상단에 짧게 보여준다.
    description: Mapped[str | None] = mapped_column(Text)

    # 매장 사진(간판·가게 내부) URL. 웹 정적 경로(img/sellers/…)나 S3 URL이 들어온다.
    # 매물 사진과는 별개의 컬럼이다 — 가게 소개 칸에 파는 물건 사진이 대신 걸리면
    # 안 되기 때문이다. 없으면 화면이 사진 칸 자체를 그리지 않는다.
    photo_url: Mapped[str | None] = mapped_column(String(300))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class AdminMemoRecord(Base):
    """
    관리자 공용 메모 — 항상 한 행(id=1)이다.

    원래 서버의 텍스트 파일 한 장이었는데, 배포가 백엔드 여러 대로 확정되면서
    성립하지 않게 됐다 — A 서버에 저장한 메모를 B 서버가 모르고, 컨테이너가
    교체되면 메모가 사라진다. 모든 인스턴스가 공유하는 저장소는 이미 하나 있다:
    DB다. 그래서 한 줄짜리 테이블로 옮겼다.

    CHECK(id = 1)로 한 행짜리임을 스키마에 박는다. 버그로 두 번째 행이 들어가면
    "어느 행이 진짜 메모인가"라는, 답이 없는 질문이 생기기 때문이다.
    """

    __tablename__ = "admin_memo"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    # autoincrement가 아니다 — 항상 1을 명시해서 넣는다(upsert 키).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)

    # 파일 시절의 mtime을 대신한다. 화면이 "마지막 저장 시각"으로 보여준다.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)