# app/tests/test_secret_scope.py

"""
비밀값의 범위 — 웹만 관리자 비밀번호를 요구하고, 크롤러는 DATABASE_URL 만으로 뜬다.

임포트 시점 동작이라 서브프로세스로 검증한다(같은 인터프리터에서 reload 하면
다른 테스트의 모듈 상태를 흔든다).
"""

import os
import subprocess
import sys

PRODUCTION_ENV = {
    "APP_ENV": "production",
    "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:5432/x",
    # 웹 모듈이 끌고 오는 저장소 가드는 이 테스트의 관심이 아니다.
    "ALLOW_LOCAL_STORAGE": "true",
    "ENABLE_CRAWLER": "false",
}


def _run(code: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("ADMIN_", "CLIENT_", "SESSION_"))
    }
    env.update(PRODUCTION_ENV)
    env.update(extra_env)
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)


def test_config_alone_starts_without_web_secrets():
    """config 임포트만으로는 죽지 않는다 — 크롤러·집계·백업이 이 경로다."""
    result = _run("import app.config, app.db.engine, app.db.repository; print('ok')", {})
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_crawler_entry_starts_without_web_secrets():
    result = _run("import app.crawler.runner; print('ok')", {})
    assert result.returncode == 0, result.stderr


def test_web_refuses_to_start_without_secrets():
    """auth 를 임포트하는 순간(웹) 세 값 중 하나라도 기본값이면 죽는다."""
    result = _run("import app.auth", {"ADMIN_PASSWORD": "x", "CLIENT_PASSWORD": "y"})
    assert result.returncode != 0
    assert "SESSION_SECRET" in result.stderr
    assert "ADMIN_PASSWORD" not in result.stderr.split("비어 있습니다")[-1]


def test_web_starts_with_all_secrets():
    result = _run(
        "import app.auth; print('ok')",
        {"ADMIN_PASSWORD": "x", "CLIENT_PASSWORD": "y", "SESSION_SECRET": "z"},
    )
    assert result.returncode == 0, result.stderr
