# app/db/locks.py

"""
Postgres 어드바이저리 락.

실시간 수집에서 같은 검색어가 동시에 여러 번 들어올 때, API를 한 번만 치기 위한
장치다. 10명이 같은 순간에 "샤넬"을 검색하면 번개장터에 요청이 10번 가는데, 그건
우리 응답이 느려지는 문제가 아니라 **상대 사이트를 두드리는 문제**다.

Redis 대신 Postgres를 쓰는 이유:
    컨테이너를 하나 더 늘리지 않는다. 어드바이저리 락은 이 용도에 필요한 것을 이미
    다 갖췄다 — 세션이 끊기면 락이 자동으로 풀리므로, 프로세스가 죽어서 락이 영영
    남는 상황이 없다. TTL을 직접 관리할 필요가 없다는 뜻이다.

    Redis가 값을 하는 지점은 "여러 요청이 한 결과를 함께 기다리는" 단일 비행 패턴인데,
    지금 설계는 그게 필요 없다. 락을 못 잡은 요청은 기다리지 않고 즉시 돌아간다 —
    DB에 이미 있는 결과를 화면이 먼저 보여주고 있으므로, 기다릴 이유가 없다.

    부하가 커져서 진짜 단일 비행이 필요해지면 그때 Redis로 올린다.

**pg_try_advisory_lock을 쓴다(대기하지 않는 버전).** pg_advisory_lock은 락이 풀릴
때까지 커넥션을 붙잡고 기다리는데, 그러면 동시 검색 10건이 커넥션 10개를 물고 늘어져
정작 살아 있는 조회 경로까지 대기가 생긴다. 업로드 라우터에서 쓰기 타임아웃을 건 것과
같은 이유다.
"""

import hashlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 락 이름공간. 어드바이저리 락은 DB 전역이라 다른 용도의 락과 번호가 겹칠 수 있다.
# 2-인자 형태(classid, objid)를 쓰면 앞자리로 용도를 갈라둘 수 있다.
LIVE_SEARCH_NAMESPACE = 4_242


def key_to_int(key: str) -> int:
    """
    문자열 키를 어드바이저리 락이 받는 32비트 정수로 접는다.

    파이썬 내장 hash()를 쓰면 안 된다 — PYTHONHASHSEED 때문에 프로세스마다 값이
    달라져서, 백엔드가 여러 대일 때 같은 검색어가 서로 다른 락 번호를 잡는다.
    그러면 락이 있으나 마나다. blake2b는 어디서 돌려도 같은 값을 준다.

    충돌이 나면 서로 다른 검색어가 같은 락을 놓고 다툰다. 최악의 결과는 한쪽이
    실시간 조회를 건너뛰는 것뿐이라(DB 결과는 그대로 나간다) 감수할 만하다.
    """
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=4).digest()

    # signed 32비트로 해석한다. Postgres의 int4 범위를 넘으면 에러가 난다.
    return int.from_bytes(digest, "big", signed=True)


@asynccontextmanager
async def try_advisory_lock(
    session: AsyncSession,
    key: str,
    *,
    namespace: int = LIVE_SEARCH_NAMESPACE,
) -> AsyncGenerator[bool]:
    """
    락을 시도한다. 잡았으면 True, 이미 누가 잡고 있으면 즉시 False.

    잡은 경우에만 블록을 빠져나갈 때 푼다. 못 잡았는데 unlock을 부르면 경고가 뜨고,
    남의 락을 푸는 것으로 오해할 여지도 생긴다.

    사용:
        async with try_advisory_lock(session, "샤넬bag") as acquired:
            if not acquired:
                return  # 다른 요청이 이미 하고 있다
            ...
    """
    lock_id = key_to_int(key)

    acquired = bool(
        (
            await session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :id)"),
                {"ns": namespace, "id": lock_id},
            )
        ).scalar()
    )

    if not acquired:
        logger.debug("실시간 수집 락을 잡지 못했습니다: %s", key)
        yield False
        return

    try:
        yield True
    finally:
        # 세션이 끊기면 어차피 풀리지만, 커넥션이 풀로 돌아가 재사용될 때를 위해
        # 명시적으로 푼다. 풀에 락을 든 채로 반납하면 다음 요청이 그 락을 물려받는다.
        await session.execute(
            text("SELECT pg_advisory_unlock(:ns, :id)"),
            {"ns": namespace, "id": lock_id},
        )
