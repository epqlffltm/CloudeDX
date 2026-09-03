# app/auth.py

"""
시연용 로그인·권한 계층.

계정은 DB가 아니라 설정에 둔다. 시연에 필요한 계정이 둘뿐이고, 회원가입이 없어서
users 테이블을 만들면 마이그레이션과 시드 스크립트가 따라붙는데 그만한 값이 없다.
회원가입이 생기는 순간 이 모듈을 users 테이블로 갈아끼우면 되고, 라우터가 보는
얼굴(current_user / require_role)은 그대로 둘 수 있게 나눠 놓았다.

암호는 평문으로 두지 않는다. 시연 계정이라도 로그가 남고 화면이 공유되므로,
PBKDF2-HMAC-SHA256으로 검증한다. 표준 라이브러리만 쓰기 때문에 의존성이 늘지 않는다.

세션은 서명 쿠키다. 서버가 상태를 들고 있지 않아 인스턴스를 늘려도 그대로 돌고,
JWT 라이브러리를 새로 넣지 않아도 된다. 쿠키 값은 이렇게 생겼다.

    {username}.{role}.{만료 epoch}.{HMAC-SHA256 서명}

서명은 SESSION_SECRET으로 만든다. 비밀키가 바뀌면 기존 쿠키는 전부 무효가 된다.
"""

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Cookie, Depends, HTTPException, Response, status

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    CLIENT_PASSWORD,
    CLIENT_SELLER_ID,
    CLIENT_USERNAME,
    COOKIE_SECURE,
    SESSION_MAX_AGE_SECONDS,
    SESSION_SECRET,
)

logger = logging.getLogger(__name__)

Role = Literal["admin", "client"]

COOKIE_NAME = "cloudedx_session"

# PBKDF2 반복 횟수. 시연 규모에서 로그인 한 번에 수십 ms면 충분하고,
# 무차별 대입에는 충분히 비싸다.
_PBKDF2_ROUNDS = 200_000


@dataclass(frozen=True)
class User:
    """
    로그인한 사용자. 라우터는 이 모양만 알면 된다.

    seller_id 는 "이 계정은 어느 판매자인가". 매물을 고쳐도 되는지는 이 값으로만
    판단한다(app/domain/ownership.py). 지금은 설정(CLIENT_SELLER_ID)에서 오지만,
    users 테이블이 생기면 그 행의 컬럼에서 온다 — 라우터는 어느 쪽이든 모른다.
    admin 과 판매자 미지정 client 는 None 이고, None 은 어떤 매물의 주인도 아니다.
    """

    username: str
    role: Role
    seller_id: int | None = None

    @property
    def display_role(self) -> str:
        return "관리자" if self.role == "admin" else "기업고객"


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)


class _Account:
    """설정에서 읽은 계정 하나. 평문 암호는 여기서만 잠깐 존재하고 해시로 남는다."""

    def __init__(self, username: str, password: str, role: Role) -> None:
        self.username = username
        self.role = role
        self._salt = secrets.token_bytes(16)
        self._digest = _hash(password, self._salt)

    def verify(self, password: str) -> bool:
        # compare_digest를 쓰는 이유: == 는 첫 다른 바이트에서 즉시 끝나서
        # 비교에 걸린 시간으로 암호를 한 글자씩 알아낼 수 있다.
        return hmac.compare_digest(self._digest, _hash(password, self._salt))


_ACCOUNTS: dict[str, _Account] = {
    ADMIN_USERNAME: _Account(ADMIN_USERNAME, ADMIN_PASSWORD, "admin"),
    CLIENT_USERNAME: _Account(CLIENT_USERNAME, CLIENT_PASSWORD, "client"),
}


def authenticate(username: str, password: str) -> User | None:
    """
    아이디·암호를 확인하고 사용자를 돌려준다. 틀리면 None.

    없는 아이디일 때도 해시 계산을 한 번 돌린다. 바로 None을 반환하면 응답이
    눈에 띄게 빨라서, 어떤 아이디가 존재하는지 응답 시간만으로 구분된다.
    """
    account = _ACCOUNTS.get(username.strip())

    if account is None:
        _hash(password, b"dummy-salt-for-timing")
        return None

    if not account.verify(password):
        return None

    return _build_user(account.username, account.role)


def _seller_for(role: Role) -> int | None:
    """
    역할 → 판매자 id. users 테이블이 생기면 여기가 조회로 바뀐다.

    모듈 전역 CLIENT_SELLER_ID 를 호출 시점에 읽는다 — 테스트가 monkeypatch 로
    바꿔 끼울 수 있어야 해서다. 계정 목록(_ACCOUNTS)처럼 임포트 시점에 굳히면 안 된다.
    """
    if role != "client":
        return None

    return CLIENT_SELLER_ID or None


def _build_user(username: str, role: Role) -> User:
    return User(username=username, role=role, seller_id=_seller_for(role))


# --------------------------------------------------------------------------
# 세션 쿠키
# --------------------------------------------------------------------------


def _sign(payload: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_session(response: Response, user: User) -> None:
    """서명 쿠키를 굽는다. 로그인 성공 직후에만 부른다."""
    expires_at = int(time.time()) + SESSION_MAX_AGE_SECONDS
    payload = f"{user.username}.{user.role}.{expires_at}"

    response.set_cookie(
        COOKIE_NAME,
        f"{payload}.{_sign(payload)}",
        max_age=SESSION_MAX_AGE_SECONDS,
        # JS에서 못 읽게 한다. XSS가 나도 세션이 바로 새어 나가지는 않는다.
        httponly=True,
        # HTTPS 연결에서만 쿠키를 보낸다. 이게 없으면 평문 HTTP 요청에도 세션이
        # 실려 나가서, 중간에 있는 누구나 그대로 주워 로그인 상태를 가져갈 수 있다.
        #
        # 로컬은 http://localhost 라 켜면 로그인이 아예 안 된다. 그래서 값을
        # 고정하지 않고 COOKIE_SECURE(기본값은 APP_ENV)에 맡긴다.
        secure=COOKIE_SECURE,
        # 화면과 API가 같은 출처라 lax로 충분하다. 외부 사이트에서 건너온
        # POST에는 쿠키가 붙지 않으므로 CSRF 표면이 줄어든다.
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    """
    로그아웃. 쿠키를 지운다.

    삭제도 발급과 같은 속성(path·secure·samesite·httponly)으로 보내야 한다.
    브라우저는 이 속성들이 일치할 때만 같은 쿠키로 보고 덮어쓴다 — 하나라도
    어긋나면 만료된 쿠키가 하나 더 생길 뿐 원래 세션은 그대로 남는다.
    """
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


def _parse_session(raw: str | None) -> User | None:
    """쿠키를 검증해 사용자로 되돌린다. 위조·만료·형식 오류는 전부 None."""
    if not raw:
        return None

    parts = raw.rsplit(".", 3)

    if len(parts) != 4:
        return None

    username, role, expires_raw, signature = parts
    payload = f"{username}.{role}.{expires_raw}"

    if not hmac.compare_digest(signature, _sign(payload)):
        return None

    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None

    if expires_at < time.time():
        return None

    if role not in ("admin", "client"):
        return None

    # 판매자 id 는 쿠키에 싣지 않는다. 쿠키에 넣으면 CLIENT_SELLER_ID 를 바꿔도
    # 기존 세션이 옛 판매자로 남는다. 매 요청 설정(나중엔 DB)에서 다시 본다.
    return _build_user(username, role)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 의존성
# --------------------------------------------------------------------------


async def current_user(
    session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User | None:
    """로그인 상태를 읽는다. 비로그인은 None — 여기서는 막지 않는다."""
    return _parse_session(session)


async def require_login(
    user: Annotated[User | None, Depends(current_user)],
) -> User:
    """로그인 필수 경로에 쓴다."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )

    return user


def require_role(role: Role):
    """
    특정 역할만 통과시키는 의존성을 만든다.

    로그인은 했지만 역할이 다르면 401이 아니라 403이다. 401은 "누구인지 모르겠다"라
    화면이 로그인 페이지로 보내야 하고, 403은 "누구인지는 알지만 권한이 없다"라
    다시 로그인해봐야 소용없다. 둘을 뭉개면 기업고객이 관리자 화면을 열었을 때
    로그인 화면으로 튕겨서 무한히 다시 로그인하게 된다.
    """

    async def guard(user: Annotated[User, Depends(require_login)]) -> User:
        if user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="이 기능에 접근할 권한이 없습니다.",
            )

        return user

    return guard
