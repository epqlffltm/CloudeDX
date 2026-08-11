# app/routers/meta.py

"""
프론트엔드가 필터 UI를 그리고 수집 현황을 표시하는 데 필요한 값을 내려주는 라우터.

브랜드/수집처 목록을 프론트에 하드코딩하면 app/crawler/brands.py를 고칠 때마다 양쪽을
같이 고쳐야 한다. 여기서 내려주면 브랜드를 추가해도 프론트 코드는 그대로 둔다.
지금 게시판(app/routers/web.py)도 같은 상수를 참조하고 있어서, 화면과 API가 같은
선택지를 보여준다.

crawler 항목이 있는 이유: 서버가 크롤링을 기다리지 않고 바로 열리기 때문에, 방금 뜬
서버는 목록이 비어 있다. 그게 "매물이 없다"인지 "아직 수집 중"인지 클라이언트가
구분할 수 있어야 한다.

수집 주기는 app.crawler.scheduler가 아니라 app.config에서 가져온다. scheduler를
임포트하면 Playwright까지 딸려 오는데, 백엔드 이미지에는 Playwright가 없다.

main.py에서 prefix="/api"를 붙여 등록하므로 실제 경로는 /api/meta다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import CRAWL_INTERVAL_MINUTES
from app.crawler.brands import LUXURY_BRANDS
from app.crawler.sources import SOURCES
from app.crawler.state import crawler_state
from app.db import repository
from app.db.engine import get_session
from app.schemas.requests import CrawledItemFilterParams
from app.schemas.responses import CrawlerStatus, MetaResponse

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get(
    "",
    response_model=MetaResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getMeta",
    summary="필터 선택지와 수집 현황",
)
async def get_meta(session: Annotated[AsyncSession, Depends(get_session)]):
    """
    필터에 쓸 수 있는 값들과 현재 수집 현황을 반환한다.

    프론트가 첫 화면을 그릴 때 한 번 호출해서 선택 상자를 채우고, 수집이 도는 동안에는
    주기적으로 다시 불러 진행 상태를 갱신하는 용도다.
    """
    # 필터를 걸지 않은 기본값으로 전체 건수를 센다.
    total = await repository.count_items(session, CrawledItemFilterParams())
    last_crawled_at = await repository.get_last_crawled_at(session)

    return MetaResponse(
        sources=list(SOURCES),
        brands=list(LUXURY_BRANDS),
        total_items=total,
        last_crawled_at=last_crawled_at,
        crawler=CrawlerStatus(
            is_running=crawler_state.is_running,
            started_at=crawler_state.started_at,
            last_finished_at=crawler_state.last_finished_at,
            last_item_count=crawler_state.last_item_count,
            last_error=crawler_state.last_error,
            rounds_completed=crawler_state.rounds_completed,
            interval_minutes=CRAWL_INTERVAL_MINUTES,
        ),
    )