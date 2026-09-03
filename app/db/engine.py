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
import ssl
import time
from collections.abc import AsyncGenerator

from prometheus_client import Counter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# app.config가 load_dotenv()를 호출하므로, 이 모듈을 임포트하는 것만으로 .env가 반영된다.
# 예전에는 호출부가 임포트 순서를 지켜야 했다.
from app.config import (
    DATABASE_RO_URL,
    DATABASE_SSL_MODE,
    DATABASE_SSL_ROOT_CERT,
    DATABASE_URL,
    IS_PRODUCTION,
    READ_FALLBACK_COOLDOWN_SECONDS,
)

logger = logging.getLogger(__name__)

# 세션이 어느 DB로 갔는지 센다.
#
# HTTP 지표(요청 수·지연·상태코드)만으로는 "페일오버 중에 읽기는 계속됐다"를 보여줄 수
# 없다. 200이 나온 것은 보이지만 그게 복제본 덕인지 아무 일도 없었던 건지 구분이 안 된다.
# target 라벨로 reader / writer / writer_fallback 이 갈리면 그래프 하나로 설명된다.
#
#   intent  read | write        엔드포인트가 요구한 것
#   target  reader              읽기 복제본으로 감
#           writer              주 DB로 감 (쓰기이거나, 복제본 미설정)
#           writer_fallback     복제본이 죽어서 주 DB로 물러섬
DB_SESSION_TOTAL = Counter(
    "cloudedx_db_session_total",
    "DB 세션 발급 수 (요청한 경로 / 실제로 간 DB)",
    ["intent", "target"],
)

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


def build_connect_args(
    *,
    ssl_mode: str = DATABASE_SSL_MODE,
    root_cert: str = DATABASE_SSL_ROOT_CERT,
    timeout: int = 10,
) -> dict:
    """
    asyncpg.connect 에 넘길 인자. 쓰기·읽기 엔진이 같은 것을 쓴다.

    timeout: DB가 죽어있을 때 OS 기본 타임아웃까지 매달려 있지 않도록 짧게 끊는다.

    ssl: 루트 CA 파일이 없으면 sslmode 문자열을 그대로 넘긴다 — asyncpg 가
         'require' 이상이면 TLS 를 강제하고 'verify-full' 이면 시스템 CA 로
         인증서와 호스트명을 본다.
         루트 CA 파일이 있으면 SSLContext 를 직접 만든다. asyncpg 의 connect() 는
         sslrootcert 를 인자로 받지 않고(DSN 쿼리나 PGSSLROOTCERT 로만), SQLAlchemy
         는 URL 을 분해해서 넘기므로 그 경로가 막혀 있다. 컨텍스트로 주면
         'verify-full' 과 같은 검증이고, 'verify-ca' 면 호스트명 검사만 끈다.
    """
    args: dict = {"timeout": timeout}

    if root_cert and ssl_mode.startswith("verify"):
        context = ssl.create_default_context(cafile=root_cert)
        context.check_hostname = ssl_mode == "verify-full"
        args["ssl"] = context
    else:
        args["ssl"] = ssl_mode

    return args


_CONNECT_ARGS = build_connect_args()

# TLS 를 강제하지 않은 채 운영으로 떴다는 것을 로그 첫 줄에 남긴다. 기동은 막지
# 않는다(EC2 자체 postgres 경로가 있다). RDS 라면 DATABASE_SSL_MODE=require 를 준다.
if IS_PRODUCTION and DATABASE_SSL_MODE in ("disable", "allow", "prefer"):
    logger.warning(
        "DATABASE_SSL_MODE=%s 로 운영 기동 — DB 연결이 평문일 수 있습니다. "
        "RDS 라면 require 이상으로 올리세요.",
        DATABASE_SSL_MODE,
    )

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # 크롤러 루프가 30분씩 자고 일어나서 DB를 쓰기 때문에, 그 사이 끊긴 커넥션을
    # 그대로 재사용하면 InterfaceError가 난다. 체크아웃할 때 살아있는지 확인하고,
    # 30분 넘은 커넥션은 폐기해서 새로 맺는다.
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args=_CONNECT_ARGS,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# 읽기 전용 엔진.
#
# DATABASE_RO_URL 이 DATABASE_URL 과 같으면(로컬·CI) 새로 만들지 않고 쓰기 엔진을
# 그대로 가리킨다. 같은 DB에 커넥션 풀을 두 벌 여는 것은 낭비이기도 하고, 로컬에서
# 풀 크기가 두 배로 보여 "커넥션이 왜 이렇게 많지"라는 착시를 만든다.
#
# 옵션은 쓰기 엔진과 동일하게 맞춘다. 복제본이라고 커넥션이 덜 끊기지 않는다.
if DATABASE_RO_URL == DATABASE_URL:
    read_engine = engine
    read_session = async_session
else:
    read_engine = create_async_engine(
        DATABASE_RO_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=_CONNECT_ARGS,
    )
    read_session = async_sessionmaker(read_engine, expire_on_commit=False)
    logger.info("읽기 복제본 사용: %s", mask_url(DATABASE_RO_URL))


async def wait_for_db(
    target: AsyncEngine | None = None,
    retries: int = 5,
    delay: float = 2.0,
) -> None:
    """
    DB에 붙을 수 있을 때까지 기다린다. 테이블은 만들지 않는다.

    docker compose up -d 직후에는 Postgres가 아직 접속을 못 받는 구간이 있어서,
    연결 계열 오류(OSError)에 한해 retries회까지 재시도한다. 비밀번호 오류나 SQL
    오류는 기다린다고 해결되지 않으므로 재시도 없이 그대로 올린다.

    target 을 주면 그 엔진을 확인한다. 기본값은 쓰기 엔진 — 인자 없이 부르던
    기존 호출부(크롤러 등)의 동작이 그대로 유지된다.
    """
    target = target if target is not None else engine
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            async with target.connect() as conn:
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
        f"  - 사용한 접속 정보: {mask_url(str(target.url))}\n"
        f"  - docker compose ps 로 db 컨테이너가 healthy인지 확인하세요.\n"
        f"  - PORTS 열에 0.0.0.0:5432->5432/tcp 처럼 화살표가 있어야 합니다."
    ) from last_exc


async def get_session() -> AsyncGenerator[AsyncSession]:
    """
    FastAPI Depends로 **쓰기** 세션을 주입한다. 주 DB로 간다.

    조회 전용 엔드포인트는 get_read_session 을 쓴다.
    """
    DB_SESSION_TOTAL.labels(intent="write", target="writer").inc()

    async with async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# 읽기 경로
# ---------------------------------------------------------------------------
#
# RDS 주 DB가 페일오버하는 60~120초 동안 읽기 복제본은 살아 있다. 읽기 경로가
# 분리되어 있으면 그 시간에도 목록/검색이 계속 돈다 — 쓰기(CSV 업로드)만 막힌다.
#
# 복제본은 자동 페일오버 대상이 아니다. 죽으면 아무도 대신 살려주지 않으므로
# 앱이 직접 쓰기 엔진으로 물러설 수 있어야 한다. 그게 아래 서킷 브레이커다.


class _ReadCircuit:
    """
    읽기 복제본 장애를 짧게 기억한다.

    요청마다 복제본에 붙어보고 실패하는 방식은 쓸 수 없다. connect_args 의
    timeout 이 10초라, 복제본이 죽어 있으면 조회 요청이 전부 10초씩 걸리다가
    폴백한다 — 사용자 입장에서는 그냥 장애다.

    한 번 실패하면 cooldown 동안 시도 자체를 건너뛰고 곧장 쓰기 엔진으로 간다.
    cooldown 이 지나면 복제본을 다시 찔러보고, 성공하면 즉시 복귀한다.

    **프로브를 한 개로 제한하지 않는다.** 쿨다운이 풀린 순간 들어온 요청이 여럿이면
    그만큼 복제본에 붙어본다. 교과서적인 half-open 은 하나만 통과시키지만, 여기서는
    그 장치를 두지 않았다 — 실패해도 각자 쓰기 엔진으로 폴백해 요청은 정상 처리되고,
    비용은 죽은 복제본에 대한 접속 시도 몇 번뿐이다. 단일 프로브를 만들려면 프로세스
    안에서는 락이, 파드 사이에서는 공유 저장소가 필요해지는데 그만한 값을 하지 않는다.

    상태는 프로세스마다 따로 있다. 파드 3개면 각자 판단하는데, 그래도 된다 —
    판단 근거가 "내 커넥션이 붙는가"라서 공유할 이유가 없고, 공유하려면
    외부 저장소가 하나 더 필요해진다.
    """

    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown = cooldown_seconds
        self._open_until = 0.0

    def is_open(self) -> bool:
        """열려 있으면 복제본을 건너뛴다."""
        return time.monotonic() < self._open_until

    def trip(self) -> None:
        self._open_until = time.monotonic() + self._cooldown

    def reset(self) -> None:
        self._open_until = 0.0


_read_circuit = _ReadCircuit(READ_FALLBACK_COOLDOWN_SECONDS)


async def _open_read_session() -> tuple[AsyncSession, str]:
    """
    읽기용 세션을 연다. 복제본이 안 되면 쓰기 엔진 세션을 돌려준다.

    핵심은 `await session.connection()` 이다. 세션 객체를 만드는 것만으로는
    아무 일도 일어나지 않고, 실제 접속은 첫 쿼리에서 일어난다 — 그때는 이미
    라우터 안이라 여기서 잡을 수가 없다. 그래서 세션을 넘기기 전에 커넥션을
    미리 확보해서, 접속 실패를 이 자리에서 확정짓는다.

    비용은 거의 없다. pool_pre_ping=True 라 어차피 체크아웃마다 확인이 들어가고,
    풀에 살아있는 커넥션이 있으면 그것을 그대로 쓴다.

    한계: 세션을 넘긴 뒤 쿼리 도중에 복제본이 죽는 경우는 여기서 못 잡는다.
    그 요청은 500으로 끝나고, 다음 요청이 이 함수에서 걸려 서킷을 연다.
    """
    if read_session is async_session:
        # 복제본이 설정되지 않은 구성(로컬·CI). 폴백을 따질 것이 없다.
        return async_session(), "writer"

    if not _read_circuit.is_open():
        session = read_session()

        try:
            await session.connection()
        except (SQLAlchemyError, OSError) as exc:
            await session.close()
            _read_circuit.trip()
            logger.warning(
                "읽기 복제본 접속 실패 (%s) — %s초간 주 DB로 보냅니다. 대상: %s",
                type(exc).__name__,
                READ_FALLBACK_COOLDOWN_SECONDS,
                mask_url(DATABASE_RO_URL),
            )
        else:
            _read_circuit.reset()
            return session, "reader"

    return async_session(), "writer_fallback"


async def get_read_session() -> AsyncGenerator[AsyncSession]:
    """
    FastAPI Depends로 **읽기** 세션을 주입한다. 조회 전용 엔드포인트에만 쓴다.

    이 세션으로 쓰기를 하면 복제본에서는 에러가 나고, 폴백 중에는 조용히 성공한다 —
    "가끔만 되는" 버그가 되므로 쓰기 경로에는 절대 붙이지 않는다.
    """
    session, target = await _open_read_session()

    DB_SESSION_TOTAL.labels(intent="read", target=target).inc()

    try:
        yield session
    finally:
        await session.close()


async def check_write_connection() -> str | None:
    """읽기와 같은 확인을 주 DB에 대해 한다. /ready 가 참고용으로 노출한다."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        return type(exc).__name__

    return None