# app/tests/test_upload_limits.py

"""
업로드 크기 제한과 쓰기 경로 실패 동작.

두 동작 모두 "정상일 때"가 아니라 "잘못됐을 때"를 규정한다. 회귀가 나도 평소에는
아무 증상이 없어서 — 5MB 넘는 파일을 아무도 안 올리고, DB는 대개 살아 있다 —
테스트로 고정해 두지 않으면 조용히 사라진다.
"""

import asyncio

import pytest
from sqlalchemy.exc import OperationalError

from app.config import MAX_UPLOAD_BYTES
from app.tests.sellers import declare_client_seller

CSV_HEADERS = {"Content-Type": "text/csv"}

VALID_CSV = (
    "title,price,url\n"
    "샤넬 클래식 플랩백 캐비어,3000000,https://example.com/1\n"
)


@pytest.fixture
async def client_session(client, session, monkeypatch):
    """
    실제 seller가 연결된 기업고객 클라이언트.

    로컬 .env의 CLIENT_SELLER_ID나 개발 DB에 남아 있는 sellers 행에 의존하지 않는다.
    CI처럼 완전히 빈 DB에서도 같은 조건으로 테스트한다.
    """
    await declare_client_seller(session, monkeypatch)

    response = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert response.status_code == 200, "테스트 계정 로그인이 실패했습니다"

    return client


class TestUploadSizeCap:
    """크기 제한은 다 읽은 뒤가 아니라 읽는 도중에 걸려야 한다."""

    async def test_선언된_크기가_넘으면_거절한다(self, client_session):
        """Content-Length 로 즉시 거절하는 빠른 경로."""
        response = await client_session.post(
            "/api/uploads/csv",
            content=b"x" * (MAX_UPLOAD_BYTES + 1),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 413

    async def test_크기를_숨겨도_거절한다(self, client_session):
        """청크 전송에도 크기 제한이 적용된다."""

        async def chunks():
            for _ in range(20):
                yield b"x" * (1024 * 1024)

        response = await client_session.post(
            "/api/uploads/csv",
            content=chunks(),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 413

    async def test_큰_본문을_통째로_메모리에_올리지_않는다(self, client_session):
        """20MB를 보내도 제한(5MB) 근처에서 멈춰야 한다."""
        import tracemalloc

        async def chunks():
            for _ in range(20):
                yield b"x" * (1024 * 1024)

        tracemalloc.start()

        try:
            response = await client_session.post(
                "/api/uploads/csv",
                content=chunks(),
                headers=CSV_HEADERS,
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert response.status_code == 413
        assert peak < MAX_UPLOAD_BYTES * 3, (
            f"본문을 통째로 버퍼링한 것으로 보입니다 (최대 {peak / 1024 / 1024:.1f}MB). "
            "크기 검사가 스트림 도중이 아니라 읽은 뒤에 걸린 것은 아닌지 확인하세요."
        )

    async def test_제한_안쪽은_그대로_통과한다(self, client_session):
        response = await client_session.post(
            "/api/uploads/csv",
            content=VALID_CSV.encode(),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["saved"] == 1


class TestWritePathFailure:
    """DB에 쓸 수 없을 때는 매달리지 말고 503으로 끊는다."""

    async def test_DB_오류는_500이_아니라_503이다(self, client_session, monkeypatch):
        async def boom(*args, **kwargs):
            raise OperationalError("INSERT", {}, Exception("주 DB 다운"))

        monkeypatch.setattr("app.db.repository.upsert_items", boom)

        response = await client_session.post(
            "/api/uploads/csv",
            content=VALID_CSV.encode(),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 503
        assert response.headers["retry-after"] == "30"

    async def test_오래_걸리면_기다리지_않고_끊는다(self, client_session, monkeypatch):
        """제한 시간을 넘기면 TimeoutError 를 503으로 바꾼다."""

        async def hang(*args, **kwargs):
            await asyncio.sleep(3600)

        monkeypatch.setattr("app.db.repository.upsert_items", hang)
        monkeypatch.setattr("app.routers.uploads.WRITE_TIMEOUT_SECONDS", 0.2)

        response = await client_session.post(
            "/api/uploads/csv",
            content=VALID_CSV.encode(),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 503

    async def test_오류_응답에_접속_정보가_없다(self, client_session, monkeypatch):
        """예외 메시지에는 접속 문자열이 섞여 나올 수 있다."""

        async def boom(*args, **kwargs):
            raise OperationalError(
                "INSERT",
                {},
                Exception("postgresql+asyncpg://cloudedx:비밀번호@db:5432/cloudedx"),
            )

        monkeypatch.setattr("app.db.repository.upsert_items", boom)

        response = await client_session.post(
            "/api/uploads/csv",
            content=VALID_CSV.encode(),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 503
        assert "비밀번호" not in response.text
        assert "postgresql" not in response.text
