# app/routers/memo.py

"""
관리자 공용 메모 — 텍스트 한 장.

게시판(/board)을 걷어내면서, 그 자리를 "관리자들끼리 쓰는 가벼운 메모장"이
대신하게 됐다. 요구가 'txt 파일처럼'이라 구현도 문자 그대로다: 글 목록도,
작성자도, 버전도 없이 **텍스트 한 장을 파일 하나에 저장**한다.

DB 테이블로 만들지 않은 이유:
    메모 하나에 테이블·마이그레이션·ORM 모델을 붙이는 것은 시연 직전에 짊어질
    무게가 아니다. 파일이면 스키마 변경이 0이고, 서버에 들어가 cat으로 읽을 수도
    있다. 대신 한계도 파일의 한계다 — 인스턴스를 여러 개 띄우면 파드마다 파일이
    갈라진다. 다중 인스턴스로 가는 날이 이 파일을 한 줄짜리 테이블로 옮기는 날이다.

저장 위치:
    web/ 아래에 두지 않는다(이미지에 구워지고 git에 들어간다 — storage.py와 같은
    이유). 업로드 볼륨(/srv/uploads) 아래에도 두지 않는다 — 그 디렉토리는 화면에
    공개 서빙되므로 관리자 메모가 주소만 알면 열리게 된다. 기본값은 리포의 data/
    인데, 컨테이너에서는 재시작에 살아남도록 ADMIN_MEMO_PATH 로 볼륨 경로를 준다.

설정을 config.py에 모으는 관행이 있지만 이 값은 소비자가 이 라우터 하나뿐이라
여기서 읽는다. 다른 곳에서도 쓰게 되면 그때 config.py로 옮긴다.

main.py에서 prefix="/api"를 붙이므로 실제 경로는 /api/admin/memo 다.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import User, require_role
from app.schemas.memo import MemoResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

MEMO_PATH = Path(os.getenv("ADMIN_MEMO_PATH", "data/admin_memo.txt"))

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


def _load() -> MemoResponse:
    """파일에서 메모를 읽는다. 파일이 없으면 빈 메모다 — 그게 초기 상태다."""
    try:
        text = MEMO_PATH.read_text(encoding="utf-8")
        updated_at = datetime.fromtimestamp(MEMO_PATH.stat().st_mtime, tz=UTC)
    except FileNotFoundError:
        return MemoResponse(text="", updated_at=None)

    return MemoResponse(text=text, updated_at=updated_at)


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
async def read_memo(user: Annotated[User, Depends(require_role("admin"))]):
    return _load()


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
    },
)
async def write_memo(
    request: Request,
    user: Annotated[User, Depends(require_role("admin"))],
):
    """
    본문(text/plain)을 메모 전체로 저장한다.

    PUT인 이유: 부분 수정이 없고 항상 전체를 덮어쓰는 멱등 연산이라서다.
    CSV 업로드·이미지 등록과 같은 이유로 multipart를 쓰지 않는다 —
    보낼 것이 텍스트 하나뿐이다.

    임시 파일에 쓴 뒤 os.replace로 바꿔치기한다. 쓰는 도중 프로세스가 죽으면
    반쪽짜리 파일이 남는데, replace는 원자적이라 옛 메모 아니면 새 메모 둘 중
    하나만 존재한다 — 인수인계 메모가 중간에서 잘린 채 남는 것이 최악이다.
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

    MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp = MEMO_PATH.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, MEMO_PATH)

    logger.info("관리자 메모 저장: %d바이트 (%s)", len(raw), user.username)

    return _load()
