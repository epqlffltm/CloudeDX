# app/schemas/sellers.py

"""
입점 판매자 응답.

**여기 담긴 값은 우리가 검증한 것이 아니다.** 사업자등록번호의 진위는 국세청 API로만
확인할 수 있는데 백엔드가 폐쇄망에 있어 나가지 못한다. 형식 검사를 통과한 값일 뿐이고,
화면 문구도 "사업자등록번호"라고만 쓴다 — "인증된 사업자"라고 쓰면 하지 않은 검증을
했다고 말하는 셈이다.
"""

from pydantic import BaseModel, Field


class SellerOut(BaseModel):
    """매물 상세에서 함께 내려주는 판매자 정보."""

    id: int
    name: str
    business_number: str = Field(
        description=(
            "사업자등록번호(3-2-5 형식). 형식 검사만 거친 값이며 국세청 진위확인은 "
            "하지 않는다 — 백엔드가 외부망에 나가지 못한다"
        )
    )
    phone: str
    has_store: bool = Field(
        description=(
            "매장 보유 여부. false면 주소와 좌표가 없는 것이 정상이고 화면은 지도를 "
            "그리지 않는다. 주소가 null인 것과 구분하기 위해 별도 필드로 둔다"
        )
    )
    address: str | None = None
    latitude: float | None = Field(
        default=None,
        description="위도. 폐쇄망이라 서버가 지오코딩하지 않는다 — 등록 시점에 정해진 값이 그대로 저장된다",
    )
    longitude: float | None = None
    description: str | None = None
    photo_url: str | None = Field(
        default=None,
        description="매장 사진(간판·내부) URL. 매물 사진과 별개다 — 없으면 화면이 사진 칸을 그리지 않는다",
    )
    item_count: int = Field(
        default=0, description="이 판매자가 등록한 매물 중 지금 목록에 보이는 건수"
    )
