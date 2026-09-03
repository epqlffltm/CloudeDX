# app/ratelimit.py

"""
프로세스 안에서 도는 호출 횟수 제한.

두 곳에서 쓴다.
    /api/auth/login   — 같은 IP가 비밀번호를 연속으로 틀리면 잠시 잠근다.
    /api/live/search  — 같은 IP가 검색어를 바꿔가며 외부 사이트를 계속 두드리는 것을 막는다.

Redis 같은 외부 저장소를 쓰지 않는 이유는, 시연 규모에서 파드 하나가 기억하는 것으로
충분하고 의존성을 늘리고 싶지 않아서다. 파드가 셋이면 상한이 세 배로 느슨해지는데,
그래도 "무제한"과 "분당 30회"는 전혀 다른 상태다. 파드를 가로지르는 제한은 앞단의
WAF rate-based rule 몫이고, 이 모듈은 WAF가 없을 때의 최소 방어선이다.

키(IP)마다 최근 시각을 deque로 들고 있고, 창(window) 밖으로 나간 시각은 볼 때마다
버린다. 키가 무한히 쌓이지 않도록 일정 횟수마다 빈 키를 청소한다.
"""

import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.config import TRUST_PROXY_HEADERS

# 몇 번 hit 할 때마다 빈 키를 정리할지. 매번 하면 O(키 수)라 부담이고, 안 하면
# 스캐너가 IP 를 바꿔가며 두드릴 때 dict 가 계속 자란다.
_SWEEP_EVERY = 256


class SlidingWindowLimiter:
    """
    창(window_seconds) 안에 limit 번까지만 허용한다.

    limit 이 0 이하이면 꺼진 상태다 — 항상 허용하고 아무것도 기록하지 않는다.
    설정으로 끄는 경로가 있어야 로컬·CI·테스트에서 다른 테스트를 방해하지 않는다.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = float(window_seconds)
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._calls = 0

    @property
    def enabled(self) -> bool:
        return self.limit > 0 and self.window > 0

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _sweep(self, now: float) -> None:
        self._calls += 1
        if self._calls % _SWEEP_EVERY:
            return
        cutoff = now - self.window
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

    def retry_after(self, key: str) -> float | None:
        """
        지금 이 키가 막혀 있으면 풀리기까지 남은 초를, 아니면 None 을 준다.
        기록하지 않는다 — "볼 뿐" 이다.
        """
        if not self.enabled:
            return None

        bucket = self._hits.get(key)
        if bucket is None:
            return None

        now = self._clock()
        self._prune(bucket, now)

        if len(bucket) < self.limit:
            return None

        return max(0.0, bucket[0] + self.window - now)

    def hit(self, key: str) -> float | None:
        """
        한 번 사용한 것으로 기록한다. 이미 상한이면 기록하지 않고 남은 초를 돌려준다.

        상한에서 기록하지 않는 이유: 막힌 뒤에도 계속 두드리는 요청까지 세면 창이
        영영 안 비워져서, 정당한 사용자가 돌아와도 풀리지 않는다.
        """
        if not self.enabled:
            return None

        now = self._clock()
        self._sweep(now)

        bucket = self._hits.setdefault(key, deque())
        self._prune(bucket, now)

        if len(bucket) >= self.limit:
            return max(0.0, bucket[0] + self.window - now)

        bucket.append(now)
        return None

    def reset(self, key: str) -> None:
        """키의 기록을 지운다. 로그인 성공 시 실패 횟수를 되돌리는 데 쓴다."""
        self._hits.pop(key, None)

    def clear(self) -> None:
        """전부 지운다. 테스트 격리용."""
        self._hits.clear()
        self._calls = 0


def client_ip(request: Request) -> str:
    """
    요청을 보낸 쪽의 IP.

    ALB 뒤에서는 request.client.host 가 전부 ALB 의 IP 라, 그것으로 세면 모든
    사용자가 한 사람으로 묶여 첫 사용자가 상한을 채우면 전원이 막힌다.
    그래서 운영(TRUST_PROXY_HEADERS)에서는 X-Forwarded-For 의 첫 값을 쓴다.

    로컬에서는 이 헤더를 믿으면 안 된다 — 누구나 헤더에 아무 IP 나 적어서 제한을
    피할 수 있다. 앞에 프록시가 있어서 헤더를 덮어쓰는 것이 보장될 때만 켠다.
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first

    if request.client is None:
        return "unknown"

    return request.client.host
