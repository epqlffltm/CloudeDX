# app/routers/health.py

"""
운영용 상태 확인 엔드포인트.

/health 와 /ready 는 목적이 다르다. 오케스트레이터(ECS, Kubernetes 등)가 서로 다른
판단에 쓰기 때문에 섞으면 안 된다.

    /health  = liveness.  "이 프로세스가 살아있나?"
               실패하면 컨테이너를 죽이고 다시 띄운다.
               그래서 DB도 크롤러도 확인하지 않는다 — DB가 잠깐 끊겼다고 앱을
               재시작하는 건 상황을 악화시킬 뿐이고, DB가 돌아오면 앱은 알아서 회복한다.

    /ready   = readiness. "이 파드가 트래픽을 받아도 되나?"
               실패하면 죽이지 않고 로드밸런서에서만 뺀다.

readiness에 마이그레이션 검사를 넣는 이유는 배포 순서 때문이다. 새 코드를 올렸는데
alembic upgrade가 아직 안 돌았다면, 그 인스턴스는 없는 컬럼을 조회하다 500을 뱉는다.
서버는 멀쩡히 떠 있으니 liveness는 통과하고, 결국 깨진 인스턴스로 트래픽이 흘러간다.
/ready가 그걸 막는다.


주 DB가 죽었을 때 왜 여전히 Ready 인가
--------------------------------------

예전에는 이 엔드포인트가 주 DB만 봤다. 그 구성은 읽기/쓰기 분리를 무의미하게 만든다.

    주 DB 페일오버 -> /ready 503 -> 파드 3개 전부 NotReady
    -> 로드밸런서 컨트롤러가 타깃 그룹에서 전부 제외 -> 사이트 전체 다운

읽기 복제본이 멀쩡히 살아 있어도 트래픽이 파드까지 닿지 못한다. 복제본을 만든 이유
자체가 사라진다. ALB 헬스체크 경로를 /health 로 돌려도 소용없다 — IP 타깃 모드에서
파드의 등록/해제는 헬스체크가 아니라 쿠버네티스 Readiness 상태를 따라간다.

그래서 readiness 판단 기준을 **읽기 경로**로 바꿨다. 조회는 이 서비스 트래픽의
대부분이고, 주 DB가 없어도 복제본으로 서빙할 수 있다. 쓰기 경로는 확인해서 본문에
싣되 ready 판정에는 넣지 않는다 — 업로드 하나가 막혔다고 파드를 빼면, 조회까지 같이
죽는다. 그건 사용자에게 더 나쁜 결과다.

    읽기 실패 -> 이 파드는 아무것도 못 한다     -> NotReady 가 맞다
    쓰기 실패 -> 조회는 된다, 업로드만 503      -> Ready 를 유지하고 지표로 알린다

쓰기 장애를 놓치는 것이 아니다. database_write 필드와 cloudedx_db_session_total
지표에 그대로 드러나고, 업로드 요청은 정직하게 실패한다. readiness 는 "이 파드를
빼는 것이 상황을 낫게 하는가"를 묻는 자리이고, 주 DB 장애에서 그 답은 아니오다.
파드를 빼도 주 DB는 돌아오지 않는다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import check_write_connection, get_read_session
from app.db.migrations import get_current_revision, get_head_revisions
from app.domain.storage import check_storage, storage_mode
from app.schemas.responses import (
    DatabaseCheck,
    MigrationCheck,
    ReadyResponse,
    StorageCheck,
)

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
    session: Annotated[AsyncSession, Depends(get_read_session)],
):
    """
    읽기 경로와 스키마 최신 여부로 준비 상태를 판정한다.

    쓰기 경로도 확인하지만 판정에는 넣지 않는다 — 위 모듈 설명 참고.

    읽기 세션을 Depends 로 받는 이유는 다른 조회 엔드포인트와 같은 경로를 확인하기
    위해서다. 여기서만 엔진을 직접 열면 "/ready 는 통과하는데 조회는 실패하는" 어긋남이
    생길 수 있고, 테스트에서 의존성을 갈아끼울 수도 없다.

    준비되지 않았어도 본문은 그대로 내려준다. 무엇 때문에 실패했는지 알아야
    조치할 수 있기 때문이다. 상태 코드만 503으로 바꾼다.
    """
    read_ok = True
    read_error: str | None = None

    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        read_ok = False
        # 예외 문자열에 접속 정보가 섞여 나올 수 있어서 타입 이름만 남긴다.
        read_error = type(exc).__name__

    write_error = await check_write_connection()

    # 저장소(이미지 업로드) 쓰기 확인. 로컬 모드에서만 실제로 써 본다.
    #
    # 이건 위의 "쓰기 DB 실패는 ready 판정에 안 넣는다"와 결이 다르다: 주 DB는
    # 외부 의존성이라 파드를 빼도 장애가 낫지 않지만, 로컬 디스크는 이 컨테이너
    # 자신의 일부다. 못 쓰면 볼륨 권한 같은 배포 설정 오류이고, compose/오케스트레이터가
    # 기동 직후 빨간불로 알려주는 것이 첫 업로드에서 500을 만나는 것보다 낫다.
    # (실제 사례: 업로드 볼륨이 root 소유로 만들어져 사진 업로드가 500 — 테스트는
    # 개발자 PC 권한으로 돌아 잡을 수 없었다.)
    #
    # S3 모드는 검사하지 않으므로 항상 통과다 — 운영(S3) readiness 의미는 변하지 않는다.
    storage_error = check_storage()
    storage_ok = storage_error is None

    # 마이그레이션 검사도 읽기 경로로 한다. 주 DB가 죽어 있어도 스키마 버전은
    # 확인할 수 있어야 하고, 복제본은 같은 스키마를 복제하고 있다.
    #
    # 복제 지연 중에는 방금 올린 마이그레이션이 아직 안 보일 수 있다. 그 구간에서는
    # 이 파드가 NotReady 로 잠깐 빠지는데, 배포 직후 몇 초의 이야기이고 방향도 안전한
    # 쪽이다 — 스키마가 덜 반영된 파드로 트래픽을 보내는 것보다 낫다.
    current = await get_current_revision(session) if read_ok else None

    heads = get_head_revisions()

    # heads가 비어 있으면(alembic 디렉터리가 없는 이미지 등) 검사할 기준이 없으므로
    # 마이그레이션 항목은 통과로 본다. DB 연결만으로 판단한다.
    up_to_date = not heads or (current is not None and current in heads)

    is_ready = read_ok and up_to_date and storage_ok

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadyResponse(
        ready=is_ready,
        database=DatabaseCheck(connected=read_ok, error=read_error),
        database_write=DatabaseCheck(connected=write_error is None, error=write_error),
        storage=StorageCheck(mode=storage_mode(), ok=storage_ok, error=storage_error),
        migration=MigrationCheck(
            current=current,
            head=heads[0] if len(heads) == 1 else None,
            heads=list(heads),
            up_to_date=up_to_date,
        ),
    )
