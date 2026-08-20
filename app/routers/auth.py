# app/routers/auth.py

"""
로그인·로그아웃·현재 사용자 조회.

세션은 서명 쿠키다(app/auth.py 참고). 토큰을 응답 본문으로 내려주지 않는 이유는,
화면이 그것을 localStorage에 넣게 되고 XSS 한 번에 그대로 새어 나가기 때문이다.
HttpOnly 쿠키는 JS가 읽지 못하고, 같은 출처라 fetch에 자동으로 실린다.

main.py에서 prefix="/api"를 붙여 등록하므로 실제 경로는 /api/auth/* 다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import User, authenticate, clear_session, current_user, issue_session
from app.schemas.auth import LoginRequest, MeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    operation_id="login",
    summary="로그인",
    responses={401: {"description": "아이디 또는 비밀번호가 올바르지 않습니다."}},
)
async def login(payload: LoginRequest, response: Response):
    """
    아이디·암호를 확인하고 세션 쿠키를 굽는다.

    실패 메시지는 아이디와 암호를 구분하지 않는다. "없는 아이디입니다"라고 알려주면
    어떤 계정이 존재하는지 확인하는 통로가 된다.
    """
    user = authenticate(payload.username, payload.password)

    if user is None:
        logger.info("로그인 실패: %s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    issue_session(response, user)
    logger.info("로그인: %s (%s)", user.username, user.role)

    return MeResponse(username=user.username, role=user.role, display_role=user.display_role)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    summary="로그아웃",
)
async def logout(response: Response):
    """쿠키를 지운다. 비로그인 상태로 불러도 성공이다 — 결과가 같기 때문이다."""
    clear_session(response)


@router.get(
    "/me",
    response_model=MeResponse | None,
    status_code=status.HTTP_200_OK,
    operation_id="getMe",
    summary="현재 로그인 상태",
)
async def me(user: Annotated[User | None, Depends(current_user)]):
    """
    로그인했으면 사용자를, 아니면 null을 준다.

    비로그인을 401이 아니라 200 + null로 주는 이유: 이건 "확인" 요청이지 보호된
    자원이 아니다. 401로 만들면 화면이 첫 로드마다 콘솔에 오류를 찍고, 정상 흐름과
    사고를 구분할 수 없게 된다.
    """
    if user is None:
        return None

    return MeResponse(username=user.username, role=user.role, display_role=user.display_role)
