# app/schemas/auth.py

"""
로그인과 CSV 업로드의 요청/응답 모델.

계정과 업로드 결과는 다른 관심사지만, 둘 다 "시연용 회원 기능"이라는 한 덩어리라
파일을 나누지 않았다. 회원 기능이 커지면 auth.py / uploads.py로 가른다.
"""

from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """로그인 요청."""

    username: str = Field(min_length=1, max_length=50, examples=["admin"])
    password: str = Field(min_length=1, max_length=200)


class MeResponse(BaseModel):
    """현재 로그인한 사용자. 화면이 이 값으로 메뉴를 갈라 그린다."""

    username: str
    role: Literal["admin", "client"]
    display_role: str = Field(description="화면 표기용. '관리자' 또는 '기업고객'")


class UploadResponse(BaseModel):
    """
    CSV 업로드 결과.

    받은 행 수와 저장된 건수를 나눠서 준다. 둘이 다르면 무엇이 걸러졌는지
    errors로 알 수 있어야 사용자가 파일을 고칠 수 있다.
    """

    total_rows: int = Field(description="데이터 행 수 (헤더 제외, 빈 줄 제외)")
    accepted: int = Field(description="검증을 통과해 저장 시도된 건수")
    saved: int = Field(description="items 테이블에 실제로 반영된 건수 (url 중복은 갱신)")
    visible: int = Field(
        description="그중 검색 목록에 노출되는 건수. saved보다 작으면 정제 규칙이 걸러낸 것이다"
    )
    skipped: int = Field(description="검증에서 걸러진 행 수")
    errors: list[str] = Field(
        default_factory=list,
        description="걸러진 이유. 최대 50건까지만 담는다",
    )
    filtered: list[str] = Field(
        default_factory=list,
        description=(
            "저장은 됐지만 정제 규칙에서 제외돼 목록에 안 뜨는 매물의 제목. "
            "대상 브랜드가 아니거나 카테고리를 판정하지 못한 경우다"
        ),
    )
