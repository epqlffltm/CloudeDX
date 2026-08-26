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

CSV_HEADERS = {"Content-Type": "text/csv"}

VALID_CSV = (
    "title,price,url\n"
    "샤넬 클래식 플랩백 캐비어,3000000,https://example.com/1\n"
)


@pytest.fixture
async def client_session(client):
    """기업고객으로 로그인한 클라이언트."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert response.status_code == 200, "테스트 계정 로그인이 실패했습니다"

    return client


class TestUploadSizeCap:
    """
    크기 제한은 다 읽은 뒤가 아니라 읽는 도중에 걸려야 한다.

    request.body() 로 전부 읽고 나서 재는 방식은 방어가 아니다. 413을 돌려줄 때쯤이면
    막으려던 수백 MB가 이미 메모리에 있다.
    """

    async def test_선언된_크기가_넘으면_거절한다(self, client_session):
        """Content-Length 로 즉시 거절하는 빠른 경로."""
        response = await client_session.post(
            "/api/uploads/csv",
            content=b"x" * (MAX_UPLOAD_BYTES + 1),
            headers=CSV_HEADERS,
        )

        assert response.status_code == 413

    async def test_크기를_숨겨도_거절한다(self, client_session):
        """
        청크 전송에는 Content-Length 가 없다. 헤더만 믿으면 그대로 통과한다.

        여기서 검증하는 것은 상태 코드보다 **읽다가 끊었는가**이다. 전부 읽은 뒤에
        쟀다면 이 테스트도 413을 받으므로, 아래 메모리 테스트와 짝으로 봐야 한다.
        """

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
        """
        20MB를 보내도 제한(5MB) 근처에서 멈춰야 한다.

        tracemalloc 은 파이썬 객체 할당만 세므로 절대값이 정밀하지는 않다. 여기서
        보려는 것은 자릿수다 — 전부 버퍼링하면 20MB대가 나오고, 도중에 끊으면
        한 자릿수 MB에 머문다.
        """
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
    """
    DB에 쓸 수 없을 때는 매달리지 말고 503으로 끊는다.

    페일오버 구간에서 이 요청은 어차피 성공하지 못한다. 커넥션 타임아웃까지
    기다리면 워커를 붙잡고, 그 사이 살아 있는 조회 경로까지 대기가 생긴다 —
    읽기/쓰기를 나눈 의미가 없어진다.
    """

    async def test_DB_오류는_500이_아니라_503이다(self, client_session, monkeypatch):
        """
        500은 "이 요청은 원래 안 되는 것"으로 읽힌다. 페일오버는 그게 아니다.
        지표에서도 앱 버그와 인프라 장애가 섞이면 안 된다.
        """

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
