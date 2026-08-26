# app/routers/admin.py

"""
관리자 전용 시스템 현황.

/api/meta가 화면 필터에 필요한 값만 준다면, 여기는 운영자가 "지금 시스템이 제대로
돌고 있나"를 판단하는 데 필요한 값을 준다. 수집처·카테고리별 분포, 최근 수집 이력,
정제에서 걸러진 비율, 비활성 사유 분포 같은 것들이다.

/api/meta에 얹지 않고 나눈 이유: 그쪽은 비로그인 화면이 첫 로드마다 부르는 경로다.
운영 지표를 거기 섞으면 누구나 볼 수 있게 되고, 화면에 필요 없는 집계 쿼리가
모든 방문자마다 돈다.

main.py에서 prefix="/api"를 붙이므로 실제 경로는 /api/admin/* 다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_role
from app.config import CRAWL_INTERVAL_MINUTES, CRAWL_RUN_TIMEOUT_MINUTES, MISSING_THRESHOLD
from app.db import crawl_runs, repository
from app.db.engine import get_read_session
from app.db.models import CrawlRun, CrawlRunStatus, ItemRecord
from app.schemas.requests import CrawledItemFilterParams

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


async def _count_by(session: AsyncSession, column, *, active_only: bool = True) -> dict[str, int]:
    """한 컬럼으로 묶어 센다. 분포를 보는 표가 여럿이라 함수로 뺐다."""
    stmt = select(column, func.count()).group_by(column)

    if active_only:
        stmt = stmt.where(ItemRecord.is_active.is_(True), ItemRecord.is_usable.is_(True))

    result = await session.execute(stmt)

    return {str(key): n for key, n in result.all() if key is not None}


@router.get(
    "/overview",
    status_code=status.HTTP_200_OK,
    operation_id="getAdminOverview",
    summary="시스템 현황 (관리자 전용)",
    responses={
        401: {"description": "로그인이 필요합니다."},
        403: {"description": "관리자 계정만 사용할 수 있습니다."},
    },
)
async def overview(
    user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_read_session)],
):
    """
    운영 지표를 한 번에 준다. 화면(web/admin.html)이 이 응답 하나로 전부 그린다.

    쿼리를 여러 번 도는 대신 엔드포인트를 여러 개로 쪼갤 수도 있지만, 화면이
    한 화면에 전부 보여주는 구조라 왕복만 늘어난다.
    """
    # 노출 기준(활성 + 정제 통과) — 목록에 실제로 보이는 것과 같은 조건
    visible = await repository.count_items(session, CrawledItemFilterParams())

    # 전체 적재량. visible과의 차이가 곧 "걸러진 양"이다.
    stored = (await session.execute(select(func.count()).select_from(ItemRecord))).scalar_one()

    inactive = (
        await session.execute(
            select(func.count()).select_from(ItemRecord).where(ItemRecord.is_active.is_(False))
        )
    ).scalar_one()

    unusable = (
        await session.execute(
            select(func.count()).select_from(ItemRecord).where(ItemRecord.is_usable.is_(False))
        )
    ).scalar_one()

    latest = await crawl_runs.get_latest_run(session)
    stale = latest is not None and crawl_runs.is_stale(latest, CRAWL_RUN_TIMEOUT_MINUTES)

    # 최근 수집 이력 10건. 실패가 연속으로 찍히면 여기서 바로 보인다.
    runs = (
        (
            await session.execute(
                select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(10)
            )
        )
        .scalars()
        .all()
    )

    return {
        "items": {
            "visible": visible,
            "stored": stored,
            "inactive": inactive,
            "unusable": unusable,
            "by_source": await _count_by(session, ItemRecord.source),
            "by_category": await repository.count_by_category(session),
            "by_brand": await _count_by(session, ItemRecord.brand),
            # 비활성 사유. 판매완료(sold)와 연속 미발견(missing)의 비율이 뒤집히면
            # 크롤링이 매물을 놓치고 있다는 신호다.
            "unavailable_reasons": await _count_by(
                session, ItemRecord.unavailable_reason, active_only=False
            ),
            # 정제에서 걸러진 이유. 특정 사유가 폭증하면 정제 규칙을 봐야 한다.
            "reject_reasons": await _count_by(
                session, ItemRecord.reject_reason, active_only=False
            ),
        },
        "crawler": {
            "is_running": latest is not None
            and latest.status == CrawlRunStatus.RUNNING
            and not stale,
            "stale": stale,
            "interval_minutes": CRAWL_INTERVAL_MINUTES,
            "missing_threshold": MISSING_THRESHOLD,
            "rounds_completed": await crawl_runs.count_successful_runs(session),
            "last_crawled_at": await repository.get_last_crawled_at(session),
            "recent_runs": [
                {
                    "id": r.id,
                    "status": r.status,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                    "item_count": r.item_count,
                    "error": r.error,
                }
                for r in runs
            ],
        },
        "viewer": {"username": user.username, "role": user.role},
    }
