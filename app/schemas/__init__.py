# app/schemas/__init__.py

"""
스키마 패키지 진입점.

기존에는 app/schemas.py 파일 하나에 응답 모델만 있었다. 요청(쿼리 파라미터) 모델이
생기면서 requests.py / responses.py로 나눴고, 여기서 다시 모아 re-export한다.

새로 코드를 쓸 때는 어느 쪽 모델인지 드러나게 하위 모듈에서 직접 가져오는 걸 권장한다:
    from app.schemas.requests import CrawledItemFilterParams
    from app.schemas.responses import CrawledItemOut
"""

from app.schemas.requests import CrawledItemFilterParams, PaginationParams
from app.schemas.responses import (
    CrawledItemListResponse,
    CrawledItemOut,
    PagedResponse,
)

__all__ = [
    "CrawledItemFilterParams",
    "CrawledItemListResponse",
    "CrawledItemOut",
    "PagedResponse",
    "PaginationParams",
]
