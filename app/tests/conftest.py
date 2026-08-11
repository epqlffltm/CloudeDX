# app/tests/conftest.py

"""
테스트 공용 픽스처.

**실제 Postgres에 붙어서 돌린다.** SQLite로 대체하지 않는 이유는 검증하려는 동작
대부분이 Postgres 고유이기 때문이다 — upsert가 쓰는 `INSERT ... ON CONFLICT DO UPDATE`,
`timestamptz`의 타임존 처리, `ilike`의 동작이 전부 다르다. SQLite에서 통과한 테스트가
운영에서 실패하면 테스트가 없느니만 못하다.

스키마는 create_all이 아니라 `alembic upgrade head`로 만든다. 그래야 마이그레이션 자체가
테스트 대상이 된다. 모델만 고치고 마이그레이션을 안 만들면 여기서 걸린다.

접속 정보는 TEST_DATABASE_URL 환경변수로 받는다. 없으면 로컬 compose 기준 기본값을
쓰되, 데이터베이스 이름 뒤에 _test를 붙여 개발용 DB를 건드리지 않게 한다.
"""

import os
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# app.config보다 먼저 .env를 읽어야 한다. 아래에서 os.getenv로 접속 정보를 확정하는데,
# 그 시점에 .env가 로드돼 있지 않으면 기본값(5432)으로 떨어진다.
load_dotenv(PROJECT_ROOT / ".env")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx_test",
)

# app.* 를 임포트하기 전에 확정해야 한다. app.config가 모듈 로드 시점에 os.getenv로
# DATABASE_URL을 읽고, app.db.engine이 그 값으로 엔진을 만들기 때문이다.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENABLE_CRAWLER"] = "false"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """
    테스트 세션 시작 전에 스키마를 최신으로 맞춘다.

    Alembic은 동기 프로세스로 돌리는 편이 안전하다. 같은 이벤트 루프 안에서
    비동기 엔진을 두 번 만들면 커넥션이 엉킬 수 있다.
    """
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(
            "테스트 DB 마이그레이션에 실패했습니다.\n"
            f"  접속 정보: {TEST_DATABASE_URL}\n"
            "  cloudedx_test 데이터베이스가 있는지 확인하세요:\n"
            "    docker compose exec db createdb -U cloudedx cloudedx_test\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    """
    테스트 하나마다 깨끗한 세션.

    **앱이 쓰는 전역 엔진(app.db.engine.engine)을 그대로 쓴다.** 별도 엔진을 만들면
    upsert_items()가 자체 세션을 만들 때 전역 엔진을 쓰기 때문에 두 엔진이 공존하게
    되고, 그 상태에서 pytest-asyncio가 테스트마다 새 이벤트 루프를 만들면
    "Task attached to a different loop" 오류가 난다.

    같은 이유로 테스트가 끝날 때마다 엔진을 dispose한다. 풀에 남은 커넥션은 이번
    테스트의 이벤트 루프에 묶여 있어서, 다음 테스트가 재사용하면 같은 오류가 난다.

    테이블은 지우고 시작한다. 롤백 방식을 쓰지 않는 이유는 upsert_items()가 자체
    세션을 만들어 커밋하기 때문이다 — 바깥 트랜잭션으로 감싸도 격리되지 않는다.
    RESTART IDENTITY로 시퀀스도 되돌려, id를 단언하는 테스트가 실행 순서에 따라
    달라지지 않게 한다.
    """
    from app.db.engine import async_session, engine

    async with async_session() as s:
        await s.execute(text("TRUNCATE items, crawl_runs RESTART IDENTITY CASCADE"))
        await s.commit()

        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """
    앱에 요청을 보내는 클라이언트.

    get_session 의존성을 테스트 세션으로 갈아끼워서, 라우터가 보는 데이터와 테스트가
    직접 넣은 데이터가 같은 트랜잭션 시야를 공유하게 한다.

    lifespan을 실행하지 않는다. lifespan은 DB 연결 확인과 크롤러 기동을 하는데,
    여기서는 둘 다 불필요하고 크롤러 임포트는 Playwright를 요구한다.
    """
    from app.db.engine import get_session
    from app.main import app

    async def override() -> AsyncGenerator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()