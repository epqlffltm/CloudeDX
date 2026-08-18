# app/tests/test_health.py

"""
/health(liveness)와 /ready(readiness) 테스트.

둘의 차이가 이 프로젝트에서 중요한 이유는 실패했을 때 오케스트레이터가 하는 일이
다르기 때문이다. /health 실패는 컨테이너 재시작, /ready 실패는 로드밸런서에서 제외.
그래서 "DB가 죽어도 /health는 200을 유지한다"가 반드시 지켜져야 한다 — 안 그러면
DB 장애가 전체 컨테이너 재시작 폭풍으로 번진다.
"""

from sqlalchemy.exc import OperationalError

from app.db import migrations


async def test_health_is_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_everything_is_fine(client):
    response = await client.get("/ready")
    body = response.json()

    assert response.status_code == 200
    assert body["ready"] is True
    assert body["database"]["connected"] is True
    assert body["migration"]["up_to_date"] is True
    assert body["migration"]["current"] == body["migration"]["head"]


async def test_ready_fails_when_schema_is_behind(client, monkeypatch):
    """
    배포 중에 새 코드가 먼저 올라가고 마이그레이션이 아직 안 돌았을 때의 상황.
    그 인스턴스는 없는 컬럼을 조회하다 500을 뱉으므로 트래픽을 받으면 안 된다.
    """
    monkeypatch.setattr(
        "app.routers.health.get_head_revisions", lambda: ("아직_적용_안_된_리비전",)
    )

    response = await client.get("/ready")
    body = response.json()

    assert response.status_code == 503
    assert body["ready"] is False
    # 무엇 때문에 실패했는지 본문으로 알 수 있어야 조치할 수 있다.
    assert body["database"]["connected"] is True
    assert body["migration"]["up_to_date"] is False


async def test_ready_fails_when_database_is_down(client, monkeypatch, session):
    async def boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("DB 다운"))

    monkeypatch.setattr(session, "execute", boom)

    response = await client.get("/ready")
    body = response.json()

    assert response.status_code == 503
    assert body["database"]["connected"] is False
    # 예외 메시지에는 접속 정보가 섞여 나올 수 있어서 타입 이름만 노출한다.
    assert body["database"]["error"] == "OperationalError"


async def test_health_survives_database_outage(client, monkeypatch, session):
    """이게 이 파일에서 가장 중요한 테스트다."""

    async def boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("DB 다운"))

    monkeypatch.setattr(session, "execute", boom)

    assert (await client.get("/health")).status_code == 200


async def test_head_revisions_are_readable():
    """
    alembic.ini를 거치지 않고 alembic/ 디렉터리를 직접 읽는다. Alembic의 Config는
    ini를 locale 인코딩으로 읽는데, 한국어 Windows에서는 CP949라 한글이 섞이면
    UnicodeDecodeError가 난다.
    """
    heads = migrations.get_head_revisions()

    assert len(heads) == 1, "마이그레이션 브랜치가 갈렸습니다. alembic heads 로 확인하세요."


async def test_root_serves_web(client):
    # 예전 계약(/board 307 리다이렉트)은 웹 화면 동거(StaticFiles mount)로
    # 대체됐다 — 이제 루트가 곧 서비스 화면이다. 상세는 test_web_static.py.
    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]