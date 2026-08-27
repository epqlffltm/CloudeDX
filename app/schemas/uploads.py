# app/schemas/uploads.py

"""매물 사진 등록 응답."""

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
