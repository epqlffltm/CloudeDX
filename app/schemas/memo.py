# app/schemas/memo.py

"""관리자 메모 응답. 요청 스키마는 없다 — 본문이 text/plain 그 자체다."""

from datetime import datetime

from pydantic import BaseModel, Field


class MemoResponse(BaseModel):
    text: str = Field(description="메모 전문")
    updated_at: datetime | None = Field(
        description="마지막 저장 시각. 한 번도 저장한 적 없으면 null"
    )
