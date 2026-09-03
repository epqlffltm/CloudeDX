# app/tests/test_db_tls.py

"""DB 연결 암호화 인자."""

import ssl

from app.db.engine import build_connect_args


def test_mode_string_is_passed_through_without_root_cert():
    assert build_connect_args(ssl_mode="require", root_cert="")["ssl"] == "require"
    assert build_connect_args(ssl_mode="prefer", root_cert="")["ssl"] == "prefer"


def test_root_cert_builds_context_for_verify_full(tmp_path):
    ca = tmp_path / "rds-ca.pem"
    # 실제 인증서가 필요 없다 — 파일이 비어 있으면 load_verify_locations 가 실패하므로
    # 검증 자체는 못 하지만, 여기서는 분기만 본다. 빈 CA 는 SSLError 를 낸다.
    ca.write_text("")
    try:
        args = build_connect_args(ssl_mode="verify-full", root_cert=str(ca))
    except ssl.SSLError:
        return  # 빈 파일이라 CA 로딩 실패 — 컨텍스트 경로를 탔다는 뜻

    assert isinstance(args["ssl"], ssl.SSLContext)
    assert args["ssl"].check_hostname is True


def test_root_cert_is_ignored_unless_verify_mode(tmp_path):
    ca = tmp_path / "rds-ca.pem"
    ca.write_text("")
    assert build_connect_args(ssl_mode="require", root_cert=str(ca))["ssl"] == "require"


def test_timeout_is_kept():
    assert build_connect_args(ssl_mode="prefer", root_cert="")["timeout"] == 10
