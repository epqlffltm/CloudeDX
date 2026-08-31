# app/db/live_runs.py

"""
실시간 검색 쿨다운 — "이 검색어를 방금 쳤는가"를 DB 한 행으로 판단한다.

예전에는 어드바이저리 락(`app/db/locks.py`)이 이 자리에 있었다. 두 가지 이유로 걷어냈다.

**첫째, 락은 동시 호출만 막았다.** 검색창에서 엔터를 연타하거나 실패한 검색어를 계속
다시 치면 요청이 순차적으로 들어온다. 앞 요청이 이미 끝났으니 락은 비어 있고, 그
요청들은 전부 번개장터로 나갔다. 우리가 막으려던 것은 "동시"가 아니라 "자주"였다.

**둘째, 락의 수명이 세션과 어긋났다.** `pg_try_advisory_lock` 은 세션 레벨이라 COMMIT
과 무관하게 유지되는데, 여기서 말하는 세션은 **물리 커넥션**이다. SQLAlchemy 의
`AsyncSession.commit()` 은 커넥션을 풀에 반납하고 다음 문장에서 다시 빌려온다. 락 블록
안에서 `upsert_items` 가 커밋하므로, 뒤이은 `pg_advisory_unlock` 이 그 락을 잡지 않은
다른 커넥션에서 실행될 수 있었다. unlock 은 예외를 던지지 않고 false 를 돌려주므로 앱은
성공했다고 믿고, 원래 커넥션은 락을 든 채 풀로 돌아간다 — 그 검색어는 이후 영영
"이미 처리 중"으로 걸린다.

쿨다운은 이 문제를 고치는 것이 아니라 **없앤다.** 아래 문장은 락을 들지 않고, 커밋
시점에 지켜야 할 상태가 커넥션에 남지 않는다.

동작
----
INSERT ... ON CONFLICT DO UPDATE 에 WHERE 를 달아 **갱신에 성공한 요청만** 통과시킨다.
같은 키로 동시에 들어온 두 요청 중 뒤엣것은 행 잠금에서 기다렸다가, 앞 요청이 커밋한
최신 시각으로 조건을 다시 평가하고 0행을 받는다. 통과·차단 판정이 문장 하나 안에서
끝나므로 "확인하고 나서 기록한다" 사이의 틈이 없다.

`now()` 가 아니라 `clock_timestamp()` 를 쓴다. `now()` 는 트랜잭션 시작 시각으로 고정된
값이라, 충돌로 대기했다가 조건을 다시 보는 이 구조에서는 실제 시각과 어긋난다 —
기다린 쪽의 `now()` 가 앞 요청이 기록한 시각보다 이를 수도 있다.

쿨다운이 0(끔)일 때는 SQL 을 아예 타지 않는다. "0은 끈다"는 설정 계약을 시간 비교의
미묘함에 맡기지 않으려는 것이고, 켜지 않은 기능 때문에 DB 를 왕복할 이유도 없다.
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 선점 한 문장에 거는 제한시간(초).
#
# 단일 행 upsert 라 정상이면 밀리초 단위다. 이 시간을 넘긴다는 것은 주 DB 가
# 페일오버 중이거나(RDS Multi-AZ 는 60~120초) 커넥션 풀이 말랐다는 뜻인데, 그때
# 기다려 봐야 얻을 것이 없다 — 화면은 이미 읽기 복제본에서 온 목록을 보여주고
# 있고, 실시간 조회는 부가 기능이다. 빨리 포기하고 status="failed" 로 넘긴다.
#
# 설정으로 빼지 않은 이유: 튜닝할 값이 아니라 "정상이면 절대 안 걸리는" 상한이다.
CLAIM_TIMEOUT_SECONDS = 2

# 시도 시각을 선점하는 한 문장.
#
# RETURNING 이 행을 돌려주면 이 요청이 이겼다는 뜻이다. rowcount 대신 RETURNING 을
# 보는 이유는, ON CONFLICT 가 걸린 문장의 rowcount 해석이 드라이버마다 미묘해서다.
_CLAIM = text(
    """
    INSERT INTO live_search_runs (search_key, last_keyword, last_attempt_at)
    VALUES (:search_key, :keyword, clock_timestamp())
    ON CONFLICT (search_key) DO UPDATE
       SET last_keyword = EXCLUDED.last_keyword,
           last_attempt_at = clock_timestamp()
     WHERE live_search_runs.last_attempt_at
           < clock_timestamp() - CAST(:cooldown AS double precision) * INTERVAL '1 second'
    RETURNING last_attempt_at
    """
)


async def claim_live_search(
    session: AsyncSession,
    *,
    search_key: str,
    keyword: str,
    cooldown_seconds: int,
) -> bool:
    """
    이 검색어로 지금 외부 조회를 해도 되는지 판단하고, 된다면 그 자리를 선점한다.

    통과하면 True. 쿨다운 안이거나 다른 요청이 방금 선점했으면 False.

    **결과와 무관하게 시도 시각을 남기고 즉시 커밋한다.** 실패한 검색어를 기록하지
    않으면 실패할수록 더 자주 두드리게 된다 — 상대 사이트가 막고 있을 때 가장 나쁜
    행동이다. 커밋을 여기서 하는 것도 같은 이유다. 뒤이은 크롤링이나 저장이 실패해
    라우터의 트랜잭션이 되돌아가도 이 기록은 남아야 한다.

    호출자는 이 함수가 커밋한다는 것을 알고 있어야 한다. 지금 호출자(live 라우터)는
    이 시점에 커밋할 것이 따로 없어서 문제가 되지 않는다.

    **DB 장애는 여기서 삼키지 않는다.** 주 DB 페일오버 중이면 예외가 그대로 올라가고,
    라우터가 그것을 status="failed" 로 바꾼다. 여기서 True 를 돌려주면 "쿨다운을
    확인하지 못한 채 외부 조회를 하는" 상태가 되는데, DB 가 흔들리는 동안이야말로
    남의 사이트에 요청을 쏟으면 안 되는 때다. 다만 CLAIM_TIMEOUT_SECONDS 를 넘겨
    매달리지는 않는다.
    """
    if cooldown_seconds <= 0:
        # 쿨다운을 끈 구성. 이 경우 같은 검색어의 동시 호출을 막는 장치가 없다.
        return True

    async with asyncio.timeout(CLAIM_TIMEOUT_SECONDS):
        row = (
            await session.execute(
                _CLAIM,
                {
                    "search_key": search_key,
                    "keyword": keyword,
                    "cooldown": float(cooldown_seconds),
                },
            )
        ).first()

        # 통과했든 걸렸든 커밋한다. 걸린 쪽도 행 잠금을 잡았다 놓는 참여자라,
        # 트랜잭션을 열어둔 채 크롤링·응답으로 넘어가면 그 시간만큼 잠금이 남는다.
        await session.commit()

    if row is None:
        logger.debug("실시간 조회 쿨다운: %s (%d초)", search_key, cooldown_seconds)
        return False

    return True
