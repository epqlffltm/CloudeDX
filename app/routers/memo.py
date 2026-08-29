# app/routers/memo.py

"""
관리자 공용 메모 — 텍스트 한 장.

게시판(/board)을 걷어내면서, 그 자리를 "관리자들끼리 쓰는 가벼운 메모장"이
대신하게 됐다. 요구가 'txt 파일처럼'이라 API도 문자 그대로다: 글 목록도,
작성자도, 버전도 없이 **텍스트 한 장을 통째로 읽고 통째로 덮어쓴다.**

저장은 DB의 한 줄짜리 테이블(admin_memo, 항상 id=1)이다. 처음에는 서버의
텍스트 파일이었는데, 배포가 백엔드 여러 대 + 컨테이너로 확정되면서 성립하지
않게 됐다 — A 서버에 저장한 메모를 B 서버가 모르고, 컨테이너가 교체되면
파일째 사라진다. 모든 인스턴스가 이미 공유하는 저장소는 DB 하나뿐이다.
("다중 인스턴스로 가는 날이 테이블로 옮기는 날이다"라고 파일 시절 docstring에
적어뒀는데, 그날이 왔다.)

읽기도 쓰기 세션(주 DB)으로 간다. 저장 직후 곧바로 다시 읽는 화면 흐름이라,
읽기 복제본의 지연이 끼면 "저장했는데 사라진" 것처럼 보인다. 관리자 전용
저빈도 경로라 주 DB로 보내는 비용은 없다시피 하다.

main.py에서 prefix="/api"를 붙이므로 실제 경로는 /api/admin/memo 다.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_role
from app.config import WRITE_TIMEOUT_SECONDS
from app.db.engine import get_session
from app.db.models import AdminMemoRecord
from app.schemas.memo import MemoResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# 메모 최대 크기. '가벼운 메모장'의 상한이지 방어선의 전부는 아니다 —
# 아래 _read_body_capped 가 읽는 도중에 끊는 것이 실제 방어다(uploads.py와 같은 원리).
MAX_MEMO_BYTES = 64 * 1024


async def _read_body_capped(request: Request, limit: int) -> bytes:
    """
    본문을 읽되 limit을 넘기면 그 자리에서 중단한다.

    다 읽은 뒤에 재면 막으려던 본문이 이미 메모리에 올라와 있다. 자세한 논리는
    app/routers/uploads.py의 같은 이름 함수 참고 — 여기서 다시 만든 이유는,
    업로드 라우터의 내부 구현을 임포트하면 그쪽을 리팩터링할 때 이쪽이 같이
    깨지기 때문이다. 열 줄짜리 중복이 결합보다 싸다.
    """
    declared = request.headers.get("content-length")

    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"메모가 너무 큽니다. 최대 {limit // 1024}KB까지 가능합니다.",
        )

    chunks: list[bytes] = []
    size = 0

    async for chunk in request.stream():
        size += len(chunk)

        if size > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"메모가 너무 큽니다. 최대 {limit // 1024}KB까지 가능합니다.",
            )

        chunks.append(chunk)

    return b"".join(chunks)


@router.get(
    "/memo",
    response_model=MemoResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getAdminMemo",
    summary="관리자 메모 읽기",
    responses={
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "관리자 계정만 사용할 수 있습니다."},
    },
)
async def read_memo(
    user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """행이 없으면 빈 메모다 — 그게 초기 상태다(파일 시절의 FileNotFoundError와 같은 의미)."""
    row = await session.get(AdminMemoRecord, 1)

    if row is None:
        return MemoResponse(text="", updated_at=None)

    return MemoResponse(text=row.text, updated_at=row.updated_at)


@router.put(
    "/memo",
    response_model=MemoResponse,
    status_code=status.HTTP_200_OK,
    operation_id="putAdminMemo",
    summary="관리자 메모 저장 (전체 덮어쓰기)",
    responses={
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "관리자 계정만 사용할 수 있습니다."},
        413: {"description": "메모가 너무 큽니다."},
        503: {"description": "지금은 저장할 수 없습니다."},
    },
)
async def write_memo(
    request: Request,
    user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    본문(text/plain)을 메모 전체로 저장한다.

    PUT인 이유: 부분 수정이 없고 항상 전체를 덮어쓰는 멱등 연산이라서다.
    CSV 업로드·이미지 등록과 같은 이유로 multipart를 쓰지 않는다 —
    보낼 것이 텍스트 하나뿐이다.

    저장은 upsert 한 방이다(INSERT ... ON CONFLICT (id) DO UPDATE).
    먼저 SELECT해서 있으면 UPDATE, 없으면 INSERT로 나누면 두 요청이 동시에
    들어왔을 때 둘 다 INSERT를 타서 한쪽이 터진다. upsert는 그 경합을 DB가
    해결한다 — 파일 시절의 os.replace(원자적 교체)와 같은 역할이다.

    DB 오류·지연은 503이다(uploads.py와 같은 계약): 서버 잘못이므로 500 대신
    "잠시 후 다시"를 명시하고, 실패해도 기존 메모는 그대로다.
    """
    raw = await _read_body_capped(request, MAX_MEMO_BYTES)

    # 인코딩이 깨진 본문은 저장 전에 거른다. 저장하고 나면 읽을 때 터진다.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UTF-8 텍스트만 저장할 수 있습니다.",
        ) from None

    now = datetime.now(UTC)

    stmt = (
        pg_insert(AdminMemoRecord)
        .values(id=1, text=text, updated_at=now)
        .on_conflict_do_update(
            index_elements=["id"], set_={"text": text, "updated_at": now}
        )
    )

    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            await session.execute(stmt)
            await session.commit()
    except (TimeoutError, SQLAlchemyError) as exc:
        await session.rollback()

        logger.warning("관리자 메모 저장 실패: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc

    logger.info("관리자 메모 저장: %d바이트 (%s)", len(raw), user.username)

    return MemoResponse(text=text, updated_at=now)
