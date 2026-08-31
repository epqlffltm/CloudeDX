# app/schemas/events.py

"""
클릭 이벤트 요청·응답.

요청은 매물 id 하나다. 세션은 쿠키에서 읽으므로 본문에 싣지 않는다 — 클라이언트가
세션 값을 골라 보낼 수 있으면 남의 세션으로 클릭을 쌓는 길이 열린다.

응답은 202 Accepted에 상태 한 단어다. 클릭 수를 돌려주지 않는다. 화면이 그 값을
그리기 시작하면 "조회수"가 되고, 그건 계약에서 뺀 값이다(schemas/products.py).
"""

from typing import Literal

from pydantic import BaseModel, Field


class ClickEventIn(BaseModel):
    item_id: int = Field(ge=1, description="눌린 매물의 id (ListingOut.id)")


class ClickEventAccepted(BaseModel):
    """
    counted   새로 센 클릭
    duplicate 같은 세션이 같은 매물을 30분 안에 다시 누름 — 세지 않았다
    """

    status: Literal["counted", "duplicate"]
