# app/routers/live.py

"""
검색어 기준 실시간 수집.

**번개장터만 대상이다.** 세 수집처 중 유일하게 브라우저가 없어서 잡 하나가 2~3초에
끝난다. 당근마켓(잡당 약 10초)과 중고나라(약 17초)는 요청 경로에 넣을 수 없다 —
검색창에서 기다릴 수 있는 시간이 아니고, 백엔드 이미지에 Playwright를 넣어야 해서
"백엔드는 읽기, 크롤러는 쓰기"라는 계층 경계도 깨진다.

동작 방식:
    화면은 먼저 DB 결과를 그린다(즉시). 그다음 이 엔드포인트를 호출하고, 끝나면
    목록을 다시 불러온다. 사용자는 기다리지 않고, 몇 초 뒤 최신 매물이 얹힌다.

수집한 것을 응답에 담지 않고 **DB에 저장한 뒤 건수만 돌려주는** 이유가 둘이다.

1. 정제를 거쳐야 한다. repository.upsert_items가 제목 정제, 브랜드 재판정, 카테고리
   분류, is_usable 판정을 건다. 건너뛰면 향수·쇼핑백이 화면에 그대로 뜬다 — 실측
   599건에서 24%였던 그 문제다. 실시간이라고 규칙을 낮출 이유가 없다.
2. 저장하면 다음 사람이 공짜로 최신을 본다. 인기 검색어일수록 자동으로 신선해지고,
   사용자 검색어가 곧 수집 우선순위가 되는 셈이다.

**같은 검색어를 자주 치지 않는다.** 이 경로는 사용자의 입력이 그대로 남의 서버로
나가는 유일한 자리다. 쿨다운(app/db/live_runs.py)이 검색어의 정규형마다 마지막 시도
시각을 DB에 남겨, 그 안에 들어온 요청은 조회 없이 status="cooldown"으로 돌려보낸다.
동시 호출과 연타를 같은 장치가 함께 막는다.

main.py에서 prefix="/api"를 붙이므로 실제 경로는 /api/live/search 다.
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    LIVE_SEARCH_COOLDOWN_SECONDS,
    LIVE_SEARCH_MAX_PAGES,
    LIVE_SEARCH_TIMEOUT_SECONDS,
)
from app.crawler.bunjang.config import BunjangCrawlerConfig
from app.crawler.bunjang.crawler import BunjangCrawler
from app.db import live_runs, repository
from app.db.engine import get_session
from app.domain.live_search import build_live_query
from app.schemas.live import LiveSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live", tags=["live"])


@router.get(
    "/search",
    response_model=LiveSearchResponse,
    status_code=status.HTTP_200_OK,
    operation_id="liveSearch",
    summary="검색어로 번개장터를 즉시 조회해 저장",
)
async def live_search(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(description="검색어. 화면 검색창에 입력한 값 그대로")],
):
    """
    검색어로 번개장터를 조회해 매물을 저장하고, 저장 건수를 반환한다.

    **실패해도 200이다.** 부가 기능이라 오류를 올리면 화면이 이미 보여주고 있는 DB
    결과 위에 빨간 오류가 뜬다. 사용자가 볼 목록은 멀쩡한데 말이다. status 필드로
    결과를 알려서 화면이 조용히 넘어가게 한다.
    """
    live = build_live_query(q)

    if live is None:
        return LiveSearchResponse(status="ignored")

    # 이 검색어를 지금 쳐도 되는지 DB에 물어보고, 된다면 그 자리를 선점한다.
    # 성공·실패와 무관하게 시도 시각이 즉시 커밋되므로, 아래에서 무엇이 터지든
    # 같은 검색어가 곧바로 다시 나가지 않는다.
    claimed = await live_runs.claim_live_search(
        session,
        search_key=live.search_key,
        keyword=live.keyword,
        cooldown_seconds=LIVE_SEARCH_COOLDOWN_SECONDS,
    )

    if not claimed:
        # 기다리지 않고 즉시 돌아간다 — 화면은 이미 DB 결과를 보여주고 있으므로
        # 기다릴 이유가 없고, 기다리면 그 시간만큼 커넥션을 붙잡는다.
        return LiveSearchResponse(status="cooldown", keyword=live.keyword)

    crawler = BunjangCrawler(
        BunjangCrawlerConfig(
            # 검색어는 이미 완성돼 있다. brand에 넣으면 저장되는 매물의 브랜드가
            # "샤넬 클래식 가방"이 되므로 자리를 나눈다.
            keyword_override=live.keyword,
            # 판정한 브랜드. 못 했으면 빈 문자열을 준다 — upsert_items가
            # 제목에서 다시 판정하고, 그 결과가 없을 때만 이 값을 쓴다.
            brand=live.brand or "",
            max_pages=LIVE_SEARCH_MAX_PAGES,
        )
    )

    try:
        async with asyncio.timeout(LIVE_SEARCH_TIMEOUT_SECONDS):
            collection = await crawler.crawl()
            saved = await repository.upsert_items(list(collection.items), session=session)
    except Exception as exc:  # noqa: BLE001
        # 넓게 잡는 것이 의도다. 이 경로의 실패는 사용자가 볼 목록에 영향을
        # 주지 않아야 하고, 상대 사이트의 응답 형태가 바뀌면 어떤 예외가
        # 올라올지 미리 알 수 없다.
        logger.warning(
            "실시간 조회 실패 ('%s'): %s: %s",
            live.keyword,
            type(exc).__name__,
            exc,
        )
        return LiveSearchResponse(status="failed", keyword=live.keyword)

    logger.info("실시간 조회: '%s' %d건 저장", live.keyword, saved)

    return LiveSearchResponse(status="saved", saved=saved, keyword=live.keyword)
