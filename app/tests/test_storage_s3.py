# app/tests/test_storage_s3.py

"""
저장 모듈의 S3 쪽 계약 — 배포 설정 오류가 언제, 어떻게 드러나는지.

실제 S3 는 없다. boto3 클라이언트 자리에 가짜를 꽂아 호출 여부와 예외만 본다.
검증 대상은 boto3 가 아니라 우리가 그 위에 얹은 규칙이다:
    - 운영에서 S3_BUCKET 누락은 기동 거부
    - 공개 주소는 리전을 알면 리전 포함
    - 저장 실패는 StorageUnavailable 하나로 닫힌다 (라우터는 503 으로 변환)
"""

import io
import os
import subprocess
import sys

import pytest
from PIL import Image

from app.domain import storage
from app.tests.sellers import declare_client_seller


class _FakeS3:
    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.calls: list[str] = []

    def put_object(self, **kwargs):
        self.calls.append("put")
        if self.fail_with is not None:
            raise self.fail_with

    def delete_object(self, **kwargs):
        self.calls.append("delete")


# ---------------------------------------------------------------------------
# 기동 가드
# ---------------------------------------------------------------------------


def test_production_without_bucket_refuses_to_start():
    """운영에서 S3_BUCKET 이 비면 RuntimeError — 조용히 로컬 디스크로 떨어지지 않는다."""
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        storage._guard_production_storage(production=True, bucket="", allow_local=False)


def test_production_with_explicit_local_opt_in_starts():
    """단일 호스트 시연은 ALLOW_LOCAL_STORAGE=true 로 명시하면 뜬다."""
    storage._guard_production_storage(production=True, bucket="", allow_local=True)


def test_local_env_without_bucket_starts():
    """로컬/CI 는 예전처럼 아무 설정 없이 뜬다."""
    storage._guard_production_storage(production=False, bucket="", allow_local=False)


def test_guard_runs_at_import():
    """
    가드가 실제로 임포트 단계에 걸려 있는지. 함수만 있고 안 부르면 의미가 없다.

    별도 프로세스로 임포트한다 — 이 프로세스에서 모듈을 reload 하면 StorageUnavailable
    클래스 객체가 새로 만들어져 라우터가 들고 있는 것과 어긋난다(except 가 못 잡는다).
    """
    env = {
        **os.environ,
        "APP_ENV": "production",
        "SESSION_SECRET": "x",
        "ADMIN_PASSWORD": "x",
        "CLIENT_PASSWORD": "x",
        "S3_BUCKET": "",
        "ALLOW_LOCAL_STORAGE": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.domain.storage"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "S3_BUCKET" in result.stderr

    # 같은 조건에 ALLOW_LOCAL_STORAGE=true 만 더하면 뜬다
    env["ALLOW_LOCAL_STORAGE"] = "true"
    ok = subprocess.run(
        [sys.executable, "-c", "import app.domain.storage"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ok.returncode == 0, ok.stderr


# ---------------------------------------------------------------------------
# 공개 주소
# ---------------------------------------------------------------------------


def test_public_base_includes_region_when_known():
    """리전을 알면 리다이렉트를 안 타는 주소를 만든다."""
    assert (
        storage._default_public_base("demo-bucket", "ap-northeast-2")
        == "https://demo-bucket.s3.ap-northeast-2.amazonaws.com"
    )


def test_public_base_falls_back_without_region():
    assert storage._default_public_base("demo-bucket", "") == "https://demo-bucket.s3.amazonaws.com"


def test_public_base_empty_without_bucket():
    assert storage._default_public_base("", "ap-northeast-2") == ""


def test_public_url_roundtrip_in_s3_mode(monkeypatch):
    """public_url 과 object_name_from_url 은 서로 역함수여야 옛 사진 삭제가 동작한다."""
    monkeypatch.setattr(storage, "S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(
        storage, "S3_PUBLIC_BASE", "https://demo-bucket.s3.ap-northeast-2.amazonaws.com"
    )

    url = storage.public_url("2026/08/abc.jpg")

    assert url == "https://demo-bucket.s3.ap-northeast-2.amazonaws.com/2026/08/abc.jpg"
    assert storage.object_name_from_url(url) == "2026/08/abc.jpg"
    # 남의 주소(수집처 CDN)는 None — 지우지 않는다
    assert storage.object_name_from_url("https://cdn.example.com/x.jpg") is None


# ---------------------------------------------------------------------------
# 저장 실패 → StorageUnavailable
# ---------------------------------------------------------------------------


def test_s3_put_failure_becomes_storage_unavailable(monkeypatch):
    """botocore 예외가 무엇이든 라우터는 StorageUnavailable 하나만 본다."""

    class ClientError(Exception):
        pass

    monkeypatch.setattr(storage, "S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(storage, "_s3", _FakeS3(fail_with=ClientError("AccessDenied")))

    with pytest.raises(storage.StorageUnavailable) as excinfo:
        storage.save_image(b"x", ".jpg")

    # 원인은 체인으로 남고, 메시지에는 타입 이름만
    assert isinstance(excinfo.value.__cause__, ClientError)
    assert "ClientError" in str(excinfo.value)


def test_s3_put_success_returns_object_name(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(storage, "S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(storage, "_s3", fake)

    name = storage.save_image(b"x", ".png")

    assert name.endswith(".png")
    assert fake.calls == ["put"]


def test_local_write_failure_becomes_storage_unavailable(monkeypatch, tmp_path):
    """로컬 모드도 같은 계약 — 볼륨 권한 오류가 500 이 아니라 503 으로 간다."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"")
    monkeypatch.setattr(storage, "S3_BUCKET", "")
    monkeypatch.setattr(storage, "UPLOAD_DIR", blocker)

    with pytest.raises(storage.StorageUnavailable):
        storage.save_image(b"x", ".jpg")


# ---------------------------------------------------------------------------
# 라우터: 저장소 실패는 503 + Retry-After
# ---------------------------------------------------------------------------


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def client_session(client, session, monkeypatch):
    # 사진은 주인만 붙일 수 있다. client 계정을 판매자 하나로 선언해 두고 로그인한다.
    await declare_client_seller(session, monkeypatch)
    response = await client.post(
        "/api/auth/login",
        json={"username": "client", "password": "client1234"},
    )
    assert response.status_code == 200
    return client


async def test_image_upload_returns_503_when_storage_is_down(client_session, monkeypatch):
    """
    S3 가 거부하면 500 이 아니라 503 + Retry-After. DB 실패와 같은 계약이다.
    직접등록 매물을 CSV 로 하나 만든 뒤 사진을 올린다.
    """
    csv = "title,price,url\n샤넬 클래식 플랩백 캐비어,3000000,https://example.com/s3-503\n"
    uploaded = await client_session.post(
        "/api/uploads/csv", content=csv.encode(), headers={"Content-Type": "text/csv"}
    )
    assert uploaded.status_code == 200

    # 사진을 붙일 수 있는 건 직접등록 매물뿐이다. 어느 것이든 상관없다.
    listing = await client_session.get("/api/products", params={"source": "직접등록"})
    body = listing.json()
    items = body["items"] if isinstance(body, dict) else body
    assert items, "직접등록 매물이 하나는 있어야 한다"
    item_id = items[0]["id"]

    class EndpointConnectionError(Exception):
        pass

    monkeypatch.setattr(storage, "S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(storage, "_s3", _FakeS3(fail_with=EndpointConnectionError("timeout")))

    response = await client_session.put(
        f"/api/uploads/items/{item_id}/image",
        content=_png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    # 예외 문자열(버킷·키)이 응답에 새지 않는다
    assert "demo-bucket" not in response.text
