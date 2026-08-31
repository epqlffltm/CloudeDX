# app/routers/events.py

"""
클릭 이벤트 수신 — POST /api/events/click.

화면이 매물 카드를 누를 때 보낸다(web/js/api.js sendClick). 응답은 202 Accepted다.
지금은 저장까지 이 요청 안에서 끝내지만, 계약을 202로 둔 이유는 나중에 앞단에
큐(SQS)를 붙여 "받았다"와 "집계했다"를 분리해도 화면이 바뀌지 않게 하기
위해서다. 그때 이 라우터는 큐에 넣고 202를 돌려주는 것으로 바뀌고, 저장 규칙
(app/db/clicks.record_click)은 큐 소비자가 그대로 쓴다.

**세션 식별.** 로그인 여부와 무관하게 익명 쿠키 `reverdi_cid`를 쓴다. 없으면
이 응답에서 굽는다(1년). DB에는 그 값의 HMAC만 남는다(app/domain/clicks).
로그인 세션 쿠키를 재활용하지 않는 이유: 대부분의 방문자는 로그인하지 않고,
로그인한 업자의 클릭을 계정에 묶어 둘 이유도 없다.

**중복.** 같은 세션·같은 매물·같은 30분 버킷은 한 번만 센다. 판정은 DB 유니크
제약이 한다. 그래서 이 라우터에는 "이미 눌렀나" 조회가 없다 — 넣어 보고 결과를
읽는다.

**실패.** 없는 매물이면 404, DB 오류·지연은 503(uploads·memo와 같은 계약).
화면은 어느 쪽이든 조용히 넘어간다 — 클릭 집계가 안 됐다고 사용자가 할 일은
없다.
"""

import asyncio
import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import COOKIE_SECURE, SESSION_SECRET, WRITE_TIMEOUT_SECONDS
from app.db.clicks import record_click
from app.db.engine import get_session
from app.domain.clicks import bucket_start, session_hash
from app.schemas.events import ClickEventAccepted, ClickEventIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

CLIENT_ID_COOKIE = "reverdi_cid"
CLIENT_ID_MAX_AGE = 365 * 24 * 60 * 60


def _ensure_client_id(response: Response, current: str | None) -> str:
    """
    익명 클라이언트 id를 돌려준다. 쿠키가 없거나 모양이 이상하면 새로 굽는다.

    32자 hex(16바이트)만 받는다. 쿠키는 클라이언트가 임의로 바꿀 수 있는 값이라,
    길이·문자 집합을 고정해 두면 해시 입력이 통제된다.
    """
    if current and len(current) == 32 and all(c in "0123456789abcdef" for c in current):
        return current

    fresh = secrets.token_hex(16)
    response.set_cookie(
        CLIENT_ID_COOKIE,
        fresh,
        max_age=CLIENT_ID_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

    return fresh


@router.post(
    "/click",
    response_model=ClickEventAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="recordClick",
    summary="매물 카드 클릭 기록",
    responses={
        404: {"description": "해당 매물을 찾을 수 없습니다."},
        503: {"description": "지금은 기록할 수 없습니다."},
    },
)
async def record_click_event(
    body: ClickEventIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    client_id: Annotated[str | None, Cookie(alias=CLIENT_ID_COOKIE)] = None,
):
    """
    클릭 한 건을 남기고 202를 돌려준다.

    본문은 매물 id 하나. 세션은 쿠키에서, 시각은 서버에서 정한다 — 둘 다 클라이언트가
    고를 수 없는 값이어야 집계를 부풀릴 수 없다.
    """
    cid = _ensure_client_id(response, client_id)
    hashed = session_hash(cid, SESSION_SECRET)
    bucket = bucket_start(datetime.now(UTC))

    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            counted = await record_click(session, body.item_id, hashed, bucket)
            await session.commit()
    except IntegrityError:
        # 유니크 충돌은 ON CONFLICT가 삼키므로 여기까지 오는 IntegrityError는
        # FK 위반 — 그런 매물이 없다는 뜻이다.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 매물을 찾을 수 없습니다.",
        ) from None
    except (TimeoutError, SQLAlchemyError) as exc:
        await session.rollback()

        logger.warning("클릭 기록 실패 (item=%d): %s: %s", body.item_id, type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="지금은 기록할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc

    return ClickEventAccepted(status="counted" if counted else "duplicate")
