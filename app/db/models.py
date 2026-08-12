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
    DateTime,
    Integer,
    MetaData,
    String,
    Text,
    func,
)
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

    # ---- 생명주기 --------------------------------------------------------
    #
    # 매물은 팔리거나 삭제되면 사이트에서 사라지는데, 크롤링 결과에 없다는 것만으로는
    # "사라졌다"고 단정할 수 없다. 수집 범위 밖으로 밀렸거나 일시적 오류일 수 있다.
    # 그래서 바로 지우지 않고 미발견 횟수를 세다가, 임계값을 넘으면 비활성 처리한다.

    # 화면에 기본 노출할지 여부. **데이터로서 유효한지가 아니다.**
    # 판매완료 매물은 is_active=false지만 시세 계산에는 오히려 중요한 입력이다 —
    # 판매중 호가는 희망가격이고 판매완료가 실거래에 가깝다. 정리한다고 지우지 말 것.
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

    # 실패 사유. 일부 사이트만 실패한 경우 status는 success지만 여기에 기록이 남는다.
    # 어떤 사이트가 왜 막혔는지가 나중에 셀렉터를 고칠 때 유일한 단서라 길이 제한을 두지 않는다.
    error: Mapped[str | None] = mapped_column(Text)