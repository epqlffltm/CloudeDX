# app/db/clicks.py

"""
클릭 기록과 인기 매물 조회.

repository.py에 섞지 않고 crawl_runs.py처럼 따로 둔다 — repository는 매물
목록·upsert의 자리고, 여기는 "누가 무엇을 눌렀나"의 자리다. 둘이 한 파일에
있으면 인기 정렬을 고치다가 목록 필터를 건드리게 된다.

record_click 하나가 쓰기의 전부다. INSERT ... ON CONFLICT DO NOTHING으로 이벤트를
넣고, 실제로 들어갔을 때만 items.click_count를 +1 한다. 중복 판정은 DB 유니크
제약이 하고, 이 함수는 그 결과(들어갔나 아닌가)만 본다. 먼저 SELECT해서 있는지
보고 없으면 INSERT하는 방식은 두 요청이 동시에 오면 둘 다 INSERT를 타서 한쪽이
터진다 — 제약에 맡기면 그 경합을 DB가 해결한다.

나중에 앞단에 큐를 붙이면 큐 소비자가 이 함수를 그대로 부르면 된다. 라우터가
직접 부르든 CronJob이 부르든 저장 규칙은 여기 하나다.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ItemClickEvent, ItemRecord
from app.domain.sources import UPLOAD


async def record_click(
    session: AsyncSession, item_id: int, session_hash: str, bucket_start: datetime
) -> bool:
    """
    클릭 한 건을 남긴다. 새로 센 클릭이면 True, 같은 버킷의 중복이면 False.

    커밋은 호출자가 한다 — 라우터가 타임아웃과 오류 응답을 한 자리에서 다루기
    위해서다(memo.py와 같은 구조). item_id가 없는 매물이면 FK 위반으로
    IntegrityError가 올라오고, 그것도 호출자가 404로 바꾼다.
    """
    stmt = (
        pg_insert(ItemClickEvent)
        .values(item_id=item_id, session_hash=session_hash, bucket_start=bucket_start)
        .on_conflict_do_nothing(
            index_elements=["item_id", "session_hash", "bucket_start"]
        )
        .returning(ItemClickEvent.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()

    if inserted is None:
        return False

    await session.execute(
        update(ItemRecord)
        .where(ItemRecord.id == item_id)
        .values(click_count=ItemRecord.click_count + 1)
    )

    return True


async def list_popular(session: AsyncSession, limit: int) -> Sequence[ItemRecord]:
    """
    대문 "인기 물품" 레일. 직접등록 매물이 앞, 그 안에서 클릭 많은 순.

    정렬 키는 세 겹이다.
      1. source == '직접등록' 먼저. 입점 판매자 매물을 앞세우는 것이 이 레일의
         목적이고, 클릭이 0이어도 크롤링 매물보다 앞이다.
      2. click_count 내림차순.
      3. 최신 발견 순(repository._order_key와 같은 기준) — 클릭 수가 같을 때
         매 요청마다 순서가 흔들리지 않게 한다.

    직접등록 매물이 limit보다 적으면 나머지를 크롤링 매물이 채운다. 별도 쿼리로
    "부족분 채우기"를 하지 않는 이유는, 정렬 키 1번이 그 일을 이미 하기 때문이다.

    활성·노출 가능(is_active, is_usable) 조건은 /api/products와 같다. 인기 레일에
    죽은 링크가 올라가면 가장 눈에 띄는 자리에서 실패한다.
    """
    posted = func.coalesce(ItemRecord.posted_at, ItemRecord.first_seen_at)

    stmt = (
        select(ItemRecord)
        .where(ItemRecord.is_active.is_(True), ItemRecord.is_usable.is_(True))
        .order_by(
            (ItemRecord.source == UPLOAD).desc(),
            ItemRecord.click_count.desc(),
            posted.desc(),
            ItemRecord.id.desc(),
        )
        .limit(limit)
    )
    result = await session.execute(stmt)

    return result.scalars().all()
