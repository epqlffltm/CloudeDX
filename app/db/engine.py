# app/db/engine.py

"""
비동기 SQLAlchemy 엔진 + 세션 팩토리.

DATABASE_URL 환경변수로 접속 정보를 받는다. 기본값은 docker-compose.yml로 띄운
로컬 Postgres 기준이라, docker compose up -d만 해두면 별도 설정 없이 그대로 동작한다.

테이블 생성은 여기서 하지 않는다 — Alembic이 관리한다. 예전에는 init_db()가
create_all()로 테이블을 만들었는데, create_all은 없는 테이블만 만들 뿐 기존 테이블에
컬럼을 추가하지 못해서 스키마가 바뀔 때마다 DB를 밀어야 했다. 운영 DB에서는 쓸 수 없는
방식이라 Alembic으로 옮겼다.
"""

import asyncio
import os
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # localhost 대신 127.0.0.1을 명시. Windows + Docker Desktop 조합에서 localhost가
    # IPv6(::1)로 먼저 풀리는데 포트 포워딩이 IPv4만 제대로 열려있어 연결 거부가 나는
    # 경우가 있어서, 이를 피하려고 IPv4를 강제한다.
    "postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # 크롤러 루프가 30분씩 자고 일어나서 DB를 쓰기 때문에, 그 사이 끊긴 커넥션을
    # 그대로 재사용하면 InterfaceError가 난다. 체크아웃할 때 살아있는지 확인하고,
    # 30분 넘은 커넥션은 폐기해서 새로 맺는다.
    pool_pre_ping=True,
    pool_recycle=1800,
    # DB가 죽어있을 때 OS 기본 타임아웃까지 매달려 있지 않도록 짧게 끊는다.
    connect_args={"timeout": 10},
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def wait_for_db(retries: int = 5, delay: float = 2.0) -> None:
    """
    DB에 붙을 수 있을 때까지 기다린다. 테이블은 만들지 않는다.

    docker compose up -d 직후에는 Postgres가 아직 접속을 못 받는 구간이 있어서,
    연결 계열 오류(OSError)에 한해 retries회까지 재시도한다. 비밀번호 오류나 SQL
    오류는 기다린다고 해결되지 않으므로 재시도 없이 그대로 올린다.
    """
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except OSError as exc:
            last_exc = exc
            print(f"[db] 연결 실패 ({attempt}/{retries}): {exc}")

            if attempt < retries:
                print(f"[db] {delay}초 후 재시도...")
                await asyncio.sleep(delay)

    raise RuntimeError(
        f"Postgres 연결에 {retries}회 실패했습니다.\n"
        f"  - 사용한 접속 정보: {DATABASE_URL}\n"
        f"  - docker compose ps 로 db 컨테이너가 healthy인지 확인하세요.\n"
        f"  - PORTS 열에 0.0.0.0:5432->5432/tcp 처럼 화살표가 있어야 합니다."
    ) from last_exc


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends로 라우터에 세션을 주입하기 위한 제너레이터."""
    async with async_session() as session:
        yield session
