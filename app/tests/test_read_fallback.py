# app/tests/test_read_fallback.py

"""
읽기 복제본 폴백과 운영 비밀값 강제에 대한 테스트.

복제본을 실제로 띄우지 않는다. 이 두 동작에서 검증할 것은 "DB가 어떻게 대답하는가"가
아니라 "붙지 못했을 때 앱이 무엇을 하는가"라서, 접속 실패를 만들어내기만 하면 된다.
CI에는 Postgres가 하나뿐이므로 복제본을 요구하면 이 테스트는 아예 못 돈다.
"""

import time

import pytest

from app.db.engine import _ReadCircuit


class TestReadCircuit:
    """복제본 장애를 기억하는 서킷 브레이커."""

    def test_처음에는_닫혀있다(self):
        circuit = _ReadCircuit(cooldown_seconds=30)

        assert not circuit.is_open()

    def test_실패하면_열린다(self):
        circuit = _ReadCircuit(cooldown_seconds=30)
        circuit.trip()

        assert circuit.is_open()

    def test_쿨다운이_지나면_다시_닫힌다(self):
        # 0초로 두면 trip 직후 이미 만료된 상태가 된다.
        # sleep 으로 기다리는 테스트는 CI에서 느리고 불안정하다.
        circuit = _ReadCircuit(cooldown_seconds=0)
        circuit.trip()

        assert not circuit.is_open()

    def test_성공하면_즉시_닫힌다(self):
        """복제본이 돌아오면 쿨다운을 기다리지 않고 바로 복귀한다."""
        circuit = _ReadCircuit(cooldown_seconds=300)
        circuit.trip()
        assert circuit.is_open()

        circuit.reset()

        assert not circuit.is_open()

    def test_열린_동안은_시간이_흘러도_열려있다(self):
        circuit = _ReadCircuit(cooldown_seconds=60)
        circuit.trip()

        # monotonic 을 쓰므로 시스템 시계를 바꿔도 영향받지 않는다.
        assert circuit.is_open()
        time.sleep(0.01)
        assert circuit.is_open()


class TestSecretEnv:
    """
    운영에서 비밀값이 비어 있으면 기동을 거부한다.

    app.config 는 임포트 시점에 값을 확정하므로, 모듈을 다시 임포트하는 대신
    헬퍼 함수를 직접 부른다. 검증 대상은 분기 규칙이지 임포트 부작용이 아니다.
    """

    def test_로컬에서는_기본값으로_진행한다(self, monkeypatch):
        from app import config

        monkeypatch.delenv("TEST_SECRET", raising=False)
        monkeypatch.setattr(config, "IS_PRODUCTION", False)

        assert config._secret_env("TEST_SECRET", "local-default") == "local-default"

    def test_운영에서_비어있으면_기동을_거부한다(self, monkeypatch):
        from app import config

        monkeypatch.delenv("TEST_SECRET", raising=False)
        monkeypatch.setattr(config, "IS_PRODUCTION", True)

        with pytest.raises(RuntimeError, match="TEST_SECRET"):
            config._secret_env("TEST_SECRET", "local-default")

    def test_운영에서도_값이_있으면_통과한다(self, monkeypatch):
        from app import config

        monkeypatch.setenv("TEST_SECRET", "from-secrets-manager")
        monkeypatch.setattr(config, "IS_PRODUCTION", True)

        assert config._secret_env("TEST_SECRET", "local-default") == "from-secrets-manager"

    def test_공백만_있는_값은_비어있는_것으로_본다(self, monkeypatch):
        """쿠버네티스 Secret 이 빈 문자열로 주입되는 사고를 잡는다."""
        from app import config

        monkeypatch.setenv("TEST_SECRET", "   ")
        monkeypatch.setattr(config, "IS_PRODUCTION", True)

        with pytest.raises(RuntimeError):
            config._secret_env("TEST_SECRET", "local-default")


class TestReadSessionWiring:
    """복제본이 설정되지 않은 구성에서 엔진이 재사용되는지."""

    def test_RO_주소가_없으면_쓰기_엔진을_재사용한다(self):
        """
        커넥션 풀이 두 벌 생기지 않아야 한다. 로컬·CI가 이 경로로 돈다.
        """
        from app.config import DATABASE_RO_URL, DATABASE_URL
        from app.db.engine import async_session, engine, read_engine, read_session

        if DATABASE_RO_URL != DATABASE_URL:
            pytest.skip("DATABASE_RO_URL 이 따로 설정된 환경")

        assert read_engine is engine
        assert read_session is async_session
