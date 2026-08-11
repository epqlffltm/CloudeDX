# alembic/env.py

"""
Alembic 실행 환경.

이 프로젝트는 비동기 엔진(asyncpg)을 쓰기 때문에 Alembic 기본 템플릿을 그대로 쓸 수
없다. Alembic의 마이그레이션 실행부는 동기 코드라, 비동기 커넥션 위에서
run_sync()로 감싸 돌려야 한다.

접속 정보는 alembic.ini가 아니라 .env의 DATABASE_URL에서 읽는다. 설정 파일에
비밀번호를 박으면 그대로 커밋되기 때문이다.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# app.* 를 임포트하기 전에 .env를 읽어야 한다 (app/main.py와 같은 이유).
load_dotenv()

from app.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 자동 생성(autogenerate)이 비교할 기준. 이 metadata와 실제 DB의 차이를 보고
# 마이그레이션 초안을 만든다. 모델에 테이블을 추가하려면 app/db/models.py에서
# Base를 상속하기만 하면 여기에 자동으로 잡힌다.
target_metadata = Base.metadata

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx",
)

# %는 configparser에서 특수문자라, 비밀번호에 들어있으면 이스케이프해야 한다.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))


def _configure(connection: Connection) -> None:
    """온라인 모드의 공통 설정."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 컬럼 타입 변경(예: String(50) -> String(100))도 자동 생성이 감지하게 한다.
        # 기본값은 False라 타입만 바꾸면 빈 마이그레이션이 나온다.
        compare_type=True,
        # server_default 변경도 감지한다.
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """
    DB에 붙지 않고 SQL 스크립트만 만든다 (alembic upgrade head --sql).

    운영 DB에 직접 붙을 권한이 없어서 DBA에게 SQL을 넘겨야 하는 상황용이다.
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """비동기 엔진으로 접속한 뒤, 동기인 마이그레이션 실행부를 run_sync로 감싸 돌린다."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
