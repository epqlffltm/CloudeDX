# app/schemas/uploads.py

"""매물 사진 등록·매물 내리기 응답."""

from pydantic import BaseModel, Field


class ImageUploadResponse(BaseModel):
    """
    저장된 사진의 정보.

    크기와 바이트 수를 함께 돌려주는 이유는, 서버가 원본을 그대로 저장하지 않기
    때문이다. 받은 이미지는 픽셀만 꺼내 JPEG로 다시 인코딩되고 긴 변이 1600px로
    줄어든다. 올린 파일과 저장된 파일이 다르다는 사실을 화면이 알 수 있어야
    "왜 용량이 줄었지"를 설명할 수 있다.
    """

    item_id: int
    image_url: str = Field(description="화면에서 쓸 주소. /uploads/ 로 시작한다")
    width: int = Field(description="저장된 이미지의 가로 픽셀. 원본과 다를 수 있다")
    height: int
    bytes: int = Field(description="저장된 파일 크기. 재인코딩 후 값이다")


class ItemDeleteResponse(BaseModel):
    """
    내린 매물의 정보.

    행을 지우지 않고 is_active=False 로 내린다. url 이 유니크 키라서 행이 남아
    있어야 같은 매물을 다시 올렸을 때 새 매물로 중복 집계되지 않고 기존 행이
    되살아난다 — 크롤링 매물의 미발견 처리와 같은 규칙이다(ItemRecord.is_active
    주석 참고). 화면에서는 목록 질의가 is_active 를 보므로 즉시 사라진다.

    title 을 함께 돌려주는 이유는 화면이 "'…' 를 내렸습니다" 라고 확인 문구를
    띄울 수 있게 하려는 것이다.
    """

    item_id: int
    title: str = Field(description="내린 매물의 제목. 확인 문구에 쓴다")
