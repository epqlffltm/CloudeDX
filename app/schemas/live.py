# app/schemas/live.py

"""
실시간 수집 응답.

수집한 매물을 담지 않고 결과 요약만 돌려준다. 화면은 이 응답을 받고 목록 API를
다시 호출한다 — 그래야 실시간으로 들어온 매물도 정제·필터·정렬을 똑같이 거친 뒤
화면에 뜬다. 여기서 매물을 직접 내려주면 그 경로만 규칙이 다른 목록이 된다.
"""

from typing import Literal

from pydantic import BaseModel, Field

LiveStatus = Literal["saved", "cooldown", "ignored", "failed"]


class LiveSearchResponse(BaseModel):
    """
    실시간 조회 한 번의 결과.

    **오류도 200으로 내려온다.** 이 기능은 부가적이라, 실패를 4xx/5xx로 올리면 화면이
    이미 보여주고 있는 DB 결과 위에 오류가 뜬다. 사용자가 볼 목록은 멀쩡한데도 말이다.
    상태를 필드로 알려서 화면이 조용히 넘어가게 한다.
    """

    status: LiveStatus = Field(
        description=(
            "saved: 조회해서 저장했다 / "
            "cooldown: 같은 검색어를 최근에 이미 조회했다 (동시 요청도 여기로 온다) / "
            "ignored: 실시간 조회를 걸 검색어가 아니다 (너무 짧거나 너무 김) / "
            "failed: 번개장터 조회에 실패했다"
        )
    )
    saved: int = Field(
        default=0,
        description=(
            "저장(upsert)한 건수. 이미 있던 매물의 갱신도 포함하므로 "
            "'새로 생긴 매물 수'가 아니다"
        ),
    )
    keyword: str = Field(
        default="",
        description="실제로 번개장터에 보낸 검색어. 사용자 입력과 다를 수 있다",
    )
