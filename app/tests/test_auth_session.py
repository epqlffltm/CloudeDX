# app/tests/test_auth_session.py
"""서버 세션 쿠키의 발급·검증·만료·로그아웃 회귀 테스트."""

from app import auth as auth_module
from app.auth import COOKIE_NAME
from app.config import SESSION_MAX_AGE_SECONDS


async def _login(client, username: str = "client", password: str = "client1234"):
    return await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


async def test_login_sets_hardened_session_cookie(client):
    response = await _login(client)

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()

    assert f"{COOKIE_NAME}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert f"max-age={SESSION_MAX_AGE_SECONDS}" in cookie


async def test_login_then_me_roundtrip(client):
    response = await _login(client)
    assert response.status_code == 200

    me = await client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json() == {
        "username": "client",
        "role": "client",
        "display_role": "기업고객",
    }


async def test_tampered_cookie_is_rejected(client):
    response = await _login(client)
    raw = response.cookies.get(COOKIE_NAME)
    assert raw

    tampered = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    client.cookies.clear()

    me = await client.get(
        "/api/auth/me",
        headers={"Cookie": f"{COOKIE_NAME}={tampered}"},
    )

    assert me.status_code == 200
    assert me.json() is None


async def test_expired_cookie_is_rejected(client):
    payload = "client.client.1"
    expired = f"{payload}.{auth_module._sign(payload)}"

    me = await client.get(
        "/api/auth/me",
        headers={"Cookie": f"{COOKIE_NAME}={expired}"},
    )

    assert me.status_code == 200
    assert me.json() is None


async def test_signed_cookie_with_invalid_role_is_rejected(client):
    payload = "client.manager.4102444800"
    cookie = f"{payload}.{auth_module._sign(payload)}"

    me = await client.get(
        "/api/auth/me",
        headers={"Cookie": f"{COOKIE_NAME}={cookie}"},
    )

    assert me.status_code == 200
    assert me.json() is None


async def test_logout_invalidates_session(client):
    assert (await _login(client)).status_code == 200
    assert (await client.get("/api/auth/me")).json()["role"] == "client"

    logout = await client.post("/api/auth/logout")

    assert logout.status_code == 204
    assert (await client.get("/api/auth/me")).json() is None
