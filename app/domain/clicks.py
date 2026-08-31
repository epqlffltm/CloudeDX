# app/domain/clicks.py

"""
클릭 집계의 순수 규칙. DB도 요청 객체도 모른다.

두 가지를 정한다.

1. **버킷** — 클릭 시각을 30분 단위로 내림한다. 같은 세션이 같은 매물을 한
   버킷 안에서 몇 번 눌러도 한 번이다. 30분인 이유: 매물을 열고 원문 사이트를
   봤다가 돌아와 다시 누르는 흐름이 보통 그 안에 끝난다. 더 길면 "다음 날 다시
   관심을 가졌다"까지 지워 버리고, 더 짧으면 연타가 그대로 집계에 들어간다.

2. **세션 해시** — 익명 쿠키 값을 SESSION_SECRET으로 HMAC한다. 원값을 DB에
   남기지 않기 위해서다. 인기 집계에 필요한 것은 "같은 사람인가"뿐이고, 그건
   해시끼리 비교하면 된다. 비밀키가 바뀌면 같은 쿠키가 다른 해시가 되지만,
   그 영향은 "그 사람의 다음 클릭이 새 세션으로 한 번 더 센다"에 그친다.

라우터(app/routers/events.py)가 이 둘을 써서 이벤트 행을 만들고, 중복 제거는
DB 유니크 제약이 맡는다(app/db/clicks.py).
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

BUCKET_MINUTES = 30

# 버킷 폭. 밖에서 "다음 버킷"을 만들 때 쓴다 (테스트가 그렇다).
BUCKET_WIDTH = timedelta(minutes=BUCKET_MINUTES)


def bucket_start(at: datetime, minutes: int = BUCKET_MINUTES) -> datetime:
    """
    시각을 `minutes` 단위로 내림한다. 10:47 → 10:30, 11:02 → 11:00.

    tz-aware 입력을 전제한다. naive datetime이 오면 어느 시간대의 10:47인지 알 수
    없고, DB 컬럼이 timestamptz라 저장 시점에 해석이 갈린다. 여기서 막는다.
    """
    if at.tzinfo is None:
        raise ValueError("bucket_start는 tz-aware datetime만 받는다")

    at = at.astimezone(UTC)
    floored_minute = (at.minute // minutes) * minutes

    return at.replace(minute=floored_minute, second=0, microsecond=0)


def session_hash(client_id: str, secret: str) -> str:
    """익명 쿠키 값 → HMAC-SHA256 hex(64자). 같은 입력·같은 키면 항상 같은 값."""
    return hmac.new(secret.encode(), client_id.encode(), hashlib.sha256).hexdigest()


def current_bucket(now: datetime | None = None) -> datetime:
    """지금 시각의 버킷. 테스트가 시각을 고정할 수 있게 now를 주입받는다."""
    return bucket_start(now or datetime.now(UTC))


__all__ = ["BUCKET_MINUTES", "BUCKET_WIDTH", "bucket_start", "current_bucket", "session_hash"]
