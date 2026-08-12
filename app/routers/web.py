# app/routers/web.py

"""
사람이 보는 게시판 화면(HTML)을 그리는 라우터.

목록(/board)에서 제목을 누르면 상세(/board/{item_id})로 들어가는 구조다.
데이터는 JSON API(/crawled-items)와 똑같이 app.db.repository를 통해 가져온다 —
화면과 API가 서로 다른 쿼리를 쓰기 시작하면 "API로는 나오는데 화면엔 없는" 상황이
생기기 때문에, 조회 경로를 하나로 묶어 둔다.

나중에 프론트엔드를 따로 붙이면 이 라우터만 걷어내면 되고, /crawled-items는 그대로
남는다. 지금은 시연용으로 Jinja2 템플릿을 쓴다.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository
from app.db.engine import get_session
from app.db.models import ItemRecord
from app.domain.brands import LUXURY_BRANDS
from app.domain.sources import SOURCES
from app.schemas.requests import CrawledItemFilterParams

router = APIRouter(prefix="/board", tags=["board"], include_in_schema=False)

# app/templates/ — 이 파일 기준 상대 경로로 잡아야 작업 디렉터리와 무관하게 동작한다.
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 경과 막대가 꽉 차는 기준일. 2주 넘게 안 팔린 매물은 전부 최대치로 보여준다.
STALE_DAYS = 14


def _as_utc(moment: datetime) -> datetime:
    """
    타임존이 없는 datetime을 UTC로 간주해 붙여준다.

    Postgres의 timestamptz + asyncpg 조합에서는 항상 tz가 붙어서 오지만, 테스트를
    SQLite로 돌리거나 컬럼 타입을 timestamp로 바꾸면 naive 값이 섞여 들어와 뺄셈에서
    TypeError가 난다. 화면이 그런 이유로 죽지 않게 여기서 한 번 정규화한다.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _relative_time(moment: datetime | None) -> str:
    """'3일 전' 같은 상대 시각 문자열. 값이 없으면 빈 문자열."""
    if moment is None:
        return ""

    seconds = (datetime.now(UTC) - _as_utc(moment)).total_seconds()

    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간 전"

    return f"{int(seconds // 86400)}일 전"


def _price_text(item: ItemRecord) -> str:
    """
    화면에 쓸 가격 문자열.

    파싱된 숫자가 있으면 천 단위 구분으로 통일해서 보여준다. 원문 문자열은 사이트마다
    표기가 제각각('4,000,000원', '400만원')이라 목록에서 세로로 정렬했을 때 읽기 나쁘다.
    파싱에 실패했으면 원문을 그대로 두고, 그것도 없으면 가격 미상으로 표시한다.
    """
    if item.price_value is not None:
        return f"{item.price_value:,}원"

    return item.price or "가격 미상"


def _to_view(item: ItemRecord) -> dict:
    """
    템플릿이 바로 쓸 수 있게 표시용 값을 미리 계산해 붙인다.

    등록 시각(posted_at)이 없는 매물은 first_seen_at으로 대체하고, 대체했다는 사실을
    is_estimated로 알려준다. 사이트가 시각을 표기하지 않은 경우인데, "우리가 처음 본
    시점"을 등록일인 것처럼 보여주면 실제보다 최근 글로 오해할 수 있기 때문이다.
    """
    posted_at = item.posted_at or item.first_seen_at
    is_estimated = item.posted_at is None

    elapsed_days = (datetime.now(UTC) - _as_utc(posted_at)).days

    return {
        "item": item,
        "price_text": _price_text(item),
        "posted_at": posted_at,
        "posted_text": _relative_time(posted_at),
        "is_estimated": is_estimated,
        # 막대 길이(%). 오래된 글일수록 길어진다.
        "stale_ratio": min(max(elapsed_days, 0) / STALE_DAYS, 1.0) * 100,
        "last_seen_text": _relative_time(item.last_seen_at),
    }


@router.get(
    "",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="매물 목록 화면",
)
async def board_list(
    request: Request,
    filters: Annotated[CrawledItemFilterParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """수집한 매물을 목록으로 보여준다. 제목을 누르면 상세로 이동한다."""
    total = await repository.count_items(session, filters)
    rows = await repository.list_items(session, filters)
    last_crawled_at = await repository.get_last_crawled_at(session)

    # 페이지 이동 링크는 현재 필터를 유지한 채 offset만 바꾼다.
    prev_offset = max(filters.offset - filters.limit, 0)
    next_offset = filters.offset + filters.limit

    return templates.TemplateResponse(
        request=request,
        name="list.html",
        context={
            "views": [_to_view(row) for row in rows],
            "filters": filters,
            "total": total,
            "brands": LUXURY_BRANDS,
            "sources": SOURCES,
            "last_crawled_text": _relative_time(last_crawled_at),
            "has_prev": filters.offset > 0,
            "has_next": next_offset < total,
            "prev_url": str(request.url.include_query_params(offset=prev_offset)),
            "next_url": str(request.url.include_query_params(offset=next_offset)),
            "current_page": filters.offset // filters.limit + 1,
            "total_pages": max((total + filters.limit - 1) // filters.limit, 1),
        },
    )


@router.get(
    "/{item_id}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="매물 상세 화면",
)
async def board_detail(
    request: Request,
    item_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    매물 단건 상세.

    본문(상품 설명)은 아직 수집하지 않는다. 지금 크롤러는 검색 결과의 카드 목록만
    훑기 때문에, 상세 내용을 채우려면 개별 매물 페이지를 한 번 더 방문해야 한다.
    그때까지는 원글 링크로 안내한다.
    """
    item = await repository.get_item(session, item_id)

    if item is None:
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"item_id": item_id},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={"view": _to_view(item)},
    )