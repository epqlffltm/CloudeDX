# app/tests/test_ratelimit.py

"""
호출 횟수 제한.

리미터 자체는 시계를 주입해서 잠들지 않고 검증한다. 로그인 잠금은 라우터를 통째로
돌린다 — 로그인은 DB 를 쓰지 않으므로 이 파일은 PostgreSQL 없이도 돈다.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.ratelimit import SlidingWindowLimiter

pytestmark = pytest.mark.anyio


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# SlidingWindowLimiter
# ---------------------------------------------------------------------------


def test_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(3, 60, clock=clock)

    assert limiter.hit("a") is None
    assert limiter.hit("a") is None
    assert limiter.hit("a") is None

    blocked = limiter.hit("a")
    assert blocked is not None
    assert 59 < blocked <= 60


def test_keys_are_independent():
    limiter = SlidingWindowLimiter(1, 60, clock=FakeClock())

    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None
    assert limiter.hit("b") is None


def test_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, 60, clock=clock)

    limiter.hit("a")
    clock.now += 30
    limiter.hit("a")
    assert limiter.hit("a") is not None

    # 첫 기록이 창 밖으로 나가면 자리 하나가 다시 생긴다.
    clock.now += 31
    assert limiter.hit("a") is None


def test_blocked_hits_are_not_recorded():
    """막힌 뒤 계속 두드려도 창이 늘어나지 않아야 정당한 사용자가 돌아올 수 있다."""
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, 60, clock=clock)

    limiter.hit("a")
    clock.now += 59
    limiter.hit("a")  # 막힘 — 기록되면 안 된다
    clock.now += 2  # 첫 기록으로부터 61초
    assert limiter.hit("a") is None


def test_retry_after_does_not_record():
    limiter = SlidingWindowLimiter(1, 60, clock=FakeClock())

    assert limiter.retry_after("a") is None
    assert limiter.retry_after("a") is None
    assert limiter.hit("a") is None


def test_reset_clears_key():
    limiter = SlidingWindowLimiter(1, 60, clock=FakeClock())

    limiter.hit("a")
    limiter.reset("a")
    assert limiter.hit("a") is None


def test_zero_limit_disables():
    limiter = SlidingWindowLimiter(0, 60, clock=FakeClock())

    for _ in range(100):
        assert limiter.hit("a") is None
    assert limiter.retry_after("a") is None


def test_sweep_drops_stale_keys():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(5, 60, clock=clock)

    for i in range(300):
        limiter.hit(f"ip-{i}")

    clock.now += 61
    for _ in range(300):
        limiter.hit("live")

    # 오래된 키는 청소됐고 살아 있는 키만 남는다.
    assert "live" in limiter._hits
    assert not any(k.startswith("ip-") for k in limiter._hits)


# ---------------------------------------------------------------------------
# /api/auth/login 잠금
# ---------------------------------------------------------------------------


@pytest.fixture
async def login_client(monkeypatch):
    from app.main import app
    from app.routers import auth as auth_router

    limiter = SlidingWindowLimiter(3, 300)
    monkeypatch.setattr(auth_router, "login_failures", limiter)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    limiter.clear()


async def _login(client: AsyncClient, password: str):
    return await client.post("/api/auth/login", json={"username": "admin", "password": password})


async def test_login_locks_after_repeated_failures(login_client):
    from app.config import ADMIN_PASSWORD

    assert (await _login(login_client, "wrong")).status_code == 401
    assert (await _login(login_client, "wrong")).status_code == 401

    # 세 번째 실패에서 곧바로 429 — 한 번 더 요청해야 알게 하지 않는다.
    res = await _login(login_client, "wrong")
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert "잠겼" in res.json()["detail"]

    # 잠긴 동안은 맞는 비밀번호도 통과하지 않는다.
    assert (await _login(login_client, ADMIN_PASSWORD)).status_code == 429


async def test_login_success_resets_counter(login_client):
    from app.config import ADMIN_PASSWORD

    assert (await _login(login_client, "wrong")).status_code == 401
    assert (await _login(login_client, "wrong")).status_code == 401
    assert (await _login(login_client, ADMIN_PASSWORD)).status_code == 200

    # 성공했으면 실패 기록이 사라져 다시 두 번은 401 이어야 한다.
    assert (await _login(login_client, "wrong")).status_code == 401
    assert (await _login(login_client, "wrong")).status_code == 401
