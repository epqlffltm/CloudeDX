# app/routers/health.py

"""
운영용 상태 확인 엔드포인트.

/health 와 /ready 는 목적이 다르다. 오케스트레이터(ECS, Kubernetes 등)가 서로 다른
판단에 쓰기 때문에 섞으면 안 된다.

    /health  = liveness.  "이 프로세스가 살아있나?"
               실패하면 컨테이너를 죽이고 다시 띄운다.
               그래서 DB도 크롤러도 확인하지 않는다 — DB가 잠깐 끊겼다고 앱을
               재시작하는 건 상황을 악화시킬 뿐이고, DB가 돌아오면 앱은 알아서 회복한다.

    /ready   = readiness. "이 프로세스가 트래픽을 받아도 되나?"
               실패하면 죽이지 않고 로드밸런서에서만 뺀다.
               DB에 붙는지, 스키마가 코드가 기대하는 리비전인지 확인한다.

readiness에 마이그레이션 검사를 넣는 이유는 배포 순서 때문이다. 새 코드를 올렸는데
alembic upgrade가 아직 안 돌았다면, 그 인스턴스는 없는 컬럼을 조회하다 500을 뱉는다.
서버는 멀쩡히 떠 있으니 liveness는 통과하고, 결국 깨진 인스턴스로 트래픽이 흘러간다.
/ready가 그걸 막는다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.migrations import get_current_revision, get_head_revisions
from app.schemas.responses import DatabaseCheck, MigrationCheck, ReadyResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    operation_id="getHealth",
    summary="프로세스 생존 확인 (liveness)",
)
def health():
    """프로세스가 살아있는지만 알려준다. 의존 서비스는 일부러 확인하지 않는다."""
    return {"status": "ok"}


@router.get(
    "/ready",
    response_model=ReadyResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getReady",
    summary="트래픽 수용 가능 여부 (readiness)",
    responses={503: {"description": "아직 트래픽을 받을 수 없는 상태입니다."}},
)
async def ready(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    DB 연결과 스키마 최신 여부를 확인한다.

    준비되지 않았어도 본문은 그대로 내려준다 — 무엇 때문에 실패했는지 알아야
    조치할 수 있기 때문이다. 상태 코드만 503으로 바꾼다.
    """
    connected = True
    error: str | None = None

    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        connected = False
        # 예외 문자열에 접속 정보가 섞여 나올 수 있어서 타입 이름만 남긴다.
        error = type(exc).__name__

    current = await get_current_revision(session) if connected else None
    heads = get_head_revisions()

    # heads가 비어 있으면(alembic 디렉터리가 없는 이미지 등) 검사할 기준이 없으므로
    # 마이그레이션 항목은 통과로 본다. DB 연결만으로 판단한다.
    up_to_date = not heads or (current is not None and current in heads)

    is_ready = connected and up_to_date

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadyResponse(
        ready=is_ready,
        database=DatabaseCheck(connected=connected, error=error),
        migration=MigrationCheck(
            current=current,
            head=heads[0] if len(heads) == 1 else None,
            heads=list(heads),
            up_to_date=up_to_date,
        ),
    )