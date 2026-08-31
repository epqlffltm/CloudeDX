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
from app.domain import storage


async def test_health_is_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_everything_is_fine(client, monkeypatch, tmp_path):
    # 저장소 프로브를 기본 경로에 맡기면 러너 환경에 따라 결과가 갈린다 — CI는
    # /srv에 못 써서 이 테스트가 503으로 깨졌다. "모든 게 정상"이라는 조건도
    # 환경에서 얻어걸리는 게 아니라 테스트가 직접 만든다(CLIENT_SELLER_ID 때와
    # 같은 교훈).
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")

    response = await client.get("/ready")
    body = response.json()

    assert response.status_code == 200
    assert body["ready"] is True
    assert body["database"]["connected"] is True
    assert body["storage"]["ok"] is True
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

async def test_ready_fails_when_upload_dir_is_not_writable(client, monkeypatch, tmp_path):
    """
    (로컬 모드) 업로드 디렉터리에 못 쓰면 NotReady다.

    실제 사례에서 나온 검사다: 컨테이너의 업로드 볼륨이 root 소유로 만들어져
    앱 계정이 못 쓰는데, 코드 테스트로는 못 잡고(테스트는 개발자 PC 권한으로 돈다)
    시연 준비 중 사진 업로드 500으로야 드러났다. /ready가 기동 직후 알려줬어야 했다.

    권한 없는 디렉터리는 OS마다 만들기 다르므로, 대신 "디렉터리 자리에 파일이 있는"
    경로를 쓴다 — mkdir가 어느 OS에서든 실패한다(FileExistsError ⊂ OSError).
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"")
    monkeypatch.setattr(storage, "UPLOAD_DIR", blocker)

    response = await client.get("/ready")
    body = response.json()

    assert response.status_code == 503
    assert body["ready"] is False
    assert body["storage"] == {"mode": "local", "ok": False, "error": "FileExistsError"}
    # 저장소 문제일 뿐 DB는 멀쩡하다 — 원인이 응답에서 구분돼야 조치할 수 있다.
    assert body["database"]["connected"] is True


class _FakeS3:
    """put/delete 호출을 세고, 지정한 예외를 던지는 가짜 boto3 클라이언트."""

    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.attempts = 0
        self.puts = 0
        self.deletes = 0

    def put_object(self, **kwargs):
        self.attempts += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.puts += 1

    def delete_object(self, **kwargs):
        self.deletes += 1


def _use_s3(monkeypatch, tmp_path, fake):
    """S3 모드로 전환하고 프로브 캐시를 비운다. 로컬 디스크는 일부러 못 쓰게 둔다."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"")
    monkeypatch.setattr(storage, "UPLOAD_DIR", blocker)
    monkeypatch.setattr(storage, "S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(storage, "_s3", fake)
    monkeypatch.setattr(storage, "_probe_ok", False)
    monkeypatch.setattr(storage, "_probe_error", None)
    monkeypatch.setattr(storage, "_probe_at", 0.0)


async def test_ready_probes_s3_once_in_s3_mode(client, monkeypatch, tmp_path):
    """
    S3 모드는 프로브 객체를 put→delete 해 보고, 성공하면 다시 묻지 않는다.

    로컬 디스크가 못 쓰는 상태여도 S3 모드에서는 그 디스크를 안 쓰므로 ready 여야 한다.
    두 번째 /ready 에서 put 횟수가 늘지 않는 것이 "한 번 성공하면 끝"의 증거다.
    """
    fake = _FakeS3()
    _use_s3(monkeypatch, tmp_path, fake)

    first = await client.get("/ready")
    second = await client.get("/ready")

    assert first.status_code == 200
    assert first.json()["storage"] == {"mode": "s3", "ok": True, "error": None}
    assert second.status_code == 200
    assert (fake.puts, fake.deletes) == (1, 1)


async def test_ready_fails_when_s3_is_misconfigured(client, monkeypatch, tmp_path):
    """
    IAM 역할이 빠졌거나 버킷 이름이 틀리면 첫 업로드가 아니라 /ready 에서 드러난다.

    실패는 곧바로 재시도하지 않는다(_PROBE_RETRY_SECONDS) — 연속 /ready 가 S3 를
    두드리지 않게. 여기서는 put 이 1회만 나갔는지로 확인한다.
    """

    class AccessDenied(Exception):
        pass

    fake = _FakeS3(fail_with=AccessDenied("403"))
    _use_s3(monkeypatch, tmp_path, fake)

    first = await client.get("/ready")
    second = await client.get("/ready")

    assert first.status_code == 503
    assert first.json()["ready"] is False
    assert first.json()["storage"] == {"mode": "s3", "ok": False, "error": "AccessDenied"}
    assert second.status_code == 503

    # 실패가 캐시됐다 — 두 번째 호출은 S3 를 다시 두드리지 않았다.
    assert fake.attempts == 1
    assert fake.deletes == 0


async def test_ready_recovers_after_s3_is_fixed(client, monkeypatch, tmp_path):
    """
    인프라가 역할을 고쳐 붙이면 파드를 재시작하지 않아도 Ready 로 돌아온다.
    재시도 간격이 지난 것으로 시계를 돌리고, 클라이언트를 성공하는 것으로 바꾼다.
    """
    broken = _FakeS3(fail_with=RuntimeError("NoCredentials"))
    _use_s3(monkeypatch, tmp_path, broken)

    assert (await client.get("/ready")).status_code == 503

    # 재시도 시각을 과거로 밀고, 이제는 되는 클라이언트로 교체
    monkeypatch.setattr(storage, "_probe_at", storage._probe_at - storage._PROBE_RETRY_SECONDS)
    monkeypatch.setattr(storage, "_s3", _FakeS3())

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["storage"]["ok"] is True
