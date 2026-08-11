# app/db/migrations.py

"""
DB에 적용된 마이그레이션 리비전을 확인하는 도우미.

/ready 엔드포인트가 "이 프로세스가 트래픽을 받아도 되는가"를 판단하는 데 쓴다.
스키마가 코드보다 뒤처져 있으면 서버는 멀쩡히 떠 있어도 쿼리에서 터지기 때문에,
배포 중에 그런 인스턴스로 트래픽이 흘러 들어가지 않게 막아야 한다.

alembic.ini를 읽지 않고 alembic/ 디렉터리를 직접 가리킨다. Alembic의 Config가
ini를 locale 인코딩으로 읽는데, 한국어 Windows에서는 그게 CP949라 파일에 한글이
섞이면 UnicodeDecodeError가 난다. 여기서는 리비전 목록만 필요하므로 ini를 아예
건너뛰는 편이 안전하다.
"""

from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# app/db/migrations.py -> app/db -> app -> 프로젝트 루트
ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


@lru_cache(maxsize=1)
def get_head_revisions() -> tuple[str, ...]:
    """
    코드가 기대하는 최신 리비전. 디스크를 읽는 작업이라 한 번만 하고 캐싱한다.

    브랜치가 갈린 상태면 head가 여럿일 수 있어서 튜플로 돌려준다.
    alembic/ 디렉터리가 없으면(마이그레이션을 뺀 이미지 등) 빈 튜플이다.
    """
    if not ALEMBIC_DIR.is_dir():
        return ()

    try:
        return tuple(ScriptDirectory(str(ALEMBIC_DIR)).get_heads())
    except Exception:
        # 리비전 파일이 깨져 있어도 /ready가 500으로 죽지는 않게 한다.
        return ()


async def get_current_revision(session: AsyncSession) -> str | None:
    """
    DB에 실제로 적용된 리비전. alembic_version 테이블을 직접 읽는다.

    테이블이 없으면(= 마이그레이션을 한 번도 안 돌린 DB) None을 반환한다.
    실패한 쿼리 때문에 세션이 잠긴 상태로 남지 않도록 롤백한다.
    """
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        return result.scalar_one_or_none()
    except SQLAlchemyError:
        await session.rollback()
        return None