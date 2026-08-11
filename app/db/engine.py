# app/db/engine.py

"""
비동기 SQLAlchemy 엔진 + 세션 팩토리.

DATABASE_URL 환경변수로 접속 정보를 받는다. 기본값은 docker-compose.yml로 띄운
로컬 Postgres 기준이라, docker compose up -d만 해두면 별도 설정 없이 그대로 동작한다.
"""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # localhost 대신 127.0.0.1을 명시. Windows + Docker Desktop 조합에서 localhost가
    # IPv6(::1)로 먼저 풀리는데 포트 포워딩이 IPv4만 제대로 열려있어 연결 거부가 나는
    # 경우가 있어서, 이를 피하려고 IPv4를 강제한다.
    "postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx",
)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """
    테이블이 없으면 생성한다. 스키마가 아직 안정되지 않은 초기 단계라 Alembic 없이
    이걸로 시작한다 — 나중에 마이그레이션이 필요해지면 Alembic 도입을 고려할 것.
    """
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends로 라우터에 세션을 주입하기 위한 제너레이터."""
    async with async_session() as session:
        yield session
