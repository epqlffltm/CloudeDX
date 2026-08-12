# app/db/engine.py

"""
비동기 SQLAlchemy 엔진 + 세션 팩토리.

접속 정보는 app/config.py의 DATABASE_URL에서 받는다. 기본값이 docker-compose.yml로 띄운
로컬 Postgres 기준이라, docker compose up -d만 해두면 별도 설정 없이 그대로 동작한다.

테이블 생성은 여기서 하지 않는다 — Alembic이 관리한다. 예전에는 init_db()가
create_all()로 테이블을 만들었는데, create_all은 없는 테이블만 만들 뿐 기존 테이블에
컬럼을 추가하지 못해서 스키마가 바뀔 때마다 DB를 밀어야 했다. 운영 DB에서는 쓸 수 없는
방식이라 Alembic으로 옮겼다.

접속 정보를 로그에 남길 때는 반드시 mask_url()을 거친다. 접속 문자열에는 비밀번호가
들어 있고, 컨테이너 로그는 CloudWatch 같은 곳에 그대로 쌓여서 접근 권한이 훨씬 넓다.
"""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# app.config가 load_dotenv()를 호출하므로, 이 모듈을 임포트하는 것만으로 .env가 반영된다.
# 예전에는 호출부가 임포트 순서를 지켜야 했다.
from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

# scheme://user:password@host  에서 password 부분만 잡는다.
_PASSWORD_PATTERN = re.compile(r"(://[^:/@]+:)[^@]*(@)")


def mask_url(url: str) -> str:
    """
    접속 문자열에서 비밀번호를 가린다. 로그와 에러 메시지에 쓴다.

    호스트/포트/DB 이름은 남긴다 — 접속이 안 될 때 확인해야 하는 정보가 대부분
    그쪽이고, 그것까지 가리면 로그를 봐도 원인을 못 찾는다.

    >>> mask_url("postgresql+asyncpg://user:secret@db:5432/cloudedx")
    'postgresql+asyncpg://user:***@db:5432/cloudedx'
    """
    return _PASSWORD_PATTERN.sub(r"\1***\2", url)


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
            logger.warning("연결 실패 (%s/%s): %s", attempt, retries, exc)

            if attempt < retries:
                logger.info("%s초 후 재시도...", delay)
                await asyncio.sleep(delay)

    raise RuntimeError(
        f"Postgres 연결에 {retries}회 실패했습니다.\n"
        f"  - 사용한 접속 정보: {mask_url(DATABASE_URL)}\n"
        f"  - docker compose ps 로 db 컨테이너가 healthy인지 확인하세요.\n"
        f"  - PORTS 열에 0.0.0.0:5432->5432/tcp 처럼 화살표가 있어야 합니다."
    ) from last_exc


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI Depends로 라우터에 세션을 주입하기 위한 제너레이터."""
    async with async_session() as session:
        yield session