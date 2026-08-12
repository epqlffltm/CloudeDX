# app/tests/test_config.py

"""
설정 읽기와 로그 형식 테스트.

여기서 검증하는 것들은 잘못돼도 **당장은 조용하다는** 공통점이 있다.
CRAWL_INTERVAL_MINUTES=0 이면 크롤러가 쉬지 않고 사이트를 두드려 차단당하고,
JOONGNA_PAGES_PER_BRAND=0 이면 "수집은 도는데 아무것도 안 쌓이는" 상태가 된다.
둘 다 며칠 뒤에야 알아채고 원인 찾기도 어렵다.
"""

import json
import logging

import pytest

from app import config


@pytest.fixture
def read_int(monkeypatch):
    """환경변수를 세팅하고 _int_env로 읽는 것을 한 번에 한다."""

    def _read(raw: str | None, default: int, minimum: int | None = None) -> int:
        if raw is None:
            monkeypatch.delenv("SOME_SETTING", raising=False)
        else:
            monkeypatch.setenv("SOME_SETTING", raw)

        return config._int_env("SOME_SETTING", default, minimum=minimum)

    return _read


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7", 7),
        ("  7  ", 7),  # 앞뒤 공백은 흔한 실수라 허용한다
        (None, 30),  # 미설정 -> 기본값
        ("", 30),  # 빈 값 -> 기본값
    ],
)
def test_reads_int(read_int, raw, expected):
    assert read_int(raw, 30) == expected


def test_falls_back_when_not_a_number(read_int):
    """
    오타 하나로 컨테이너가 부팅에 실패하면 곤란하므로, 예외 대신 기본값으로 진행한다.
    """
    assert read_int("삼십", 30) == 30
    assert read_int("30분", 30) == 30


@pytest.mark.parametrize("raw", ["0", "-1", "-100"])
def test_rejects_values_below_minimum(read_int, raw):
    """
    0이나 음수를 그대로 쓰면 증상이 한참 뒤에 엉뚱하게 나타난다.
    수집 주기 0은 사이트를 쉬지 않고 두드리는 것과 같다.
    """
    assert read_int(raw, 30, minimum=1) == 30


def test_allows_minimum_itself(read_int):
    assert read_int("1", 30, minimum=1) == 1


def test_crawl_settings_have_lower_bounds():
    """
    실제 설정값들이 검증을 거치는지 본다. minimum을 빼먹으면 이 테스트가 잡는다.
    """
    assert config.CRAWL_INTERVAL_MINUTES >= 1
    assert config.CRAWL_RETRY_MINUTES >= 1
    assert config.JOONGNA_PAGES_PER_BRAND >= 1
    assert config.CRAWL_RUN_TIMEOUT_MINUTES >= 1


def test_retry_is_shorter_than_interval():
    """
    실패 후 대기가 정상 주기보다 길면 재시도의 의미가 없다. 일시적인 문제로
    주기 전체를 버리지 않으려고 짧게 잡은 값이다.
    """
    assert config.CRAWL_RETRY_MINUTES <= config.CRAWL_INTERVAL_MINUTES


# ---------------------------------------------------------------------------
# 로그 형식
# ---------------------------------------------------------------------------


def make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.crawler.runner",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="라운드 완료: %d건",
        args=(655,),
        exc_info=None,
    )

    for key, value in extra.items():
        setattr(record, key, value)

    return record


def test_json_formatter_emits_one_line_object():
    """
    로그 수집기가 필드 단위로 질의하려면 한 줄에 완결된 JSON이어야 한다.
    """
    from app.logging_config import JsonFormatter

    line = JsonFormatter().format(make_record())
    payload = json.loads(line)

    assert "\n" not in line
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.crawler.runner"
    assert payload["message"] == "라운드 완료: 655건"
    assert "time" in payload


def test_json_formatter_keeps_korean_readable():
    """ensure_ascii=False 가 빠지면 한글이 \\uXXXX 로 깨져 로그를 읽을 수 없다."""
    from app.logging_config import JsonFormatter

    record = make_record()
    record.msg = "당근마켓 수집 완료"
    record.args = ()

    assert "당근마켓" in JsonFormatter().format(record)


def test_json_formatter_includes_extra_fields():
    """
    logger.info(..., extra={"brand": "샤넬"}) 로 넘긴 값이 필드로 실려야
    "어느 브랜드에서 실패했나" 같은 질의를 할 수 있다.
    """
    from app.logging_config import JsonFormatter

    payload = json.loads(JsonFormatter().format(make_record(brand="샤넬", source="당근마켓")))

    assert payload["brand"] == "샤넬"
    assert payload["source"] == "당근마켓"
    # LogRecord 기본 속성은 섞여 들어오면 안 된다.
    assert "pathname" not in payload
    assert "levelno" not in payload


def test_setup_logging_does_not_duplicate_handlers():
    """
    uvicorn이 자기 핸들러를 먼저 붙이는 경우가 있어, 그대로 두면 같은 줄이 두 번 찍힌다.
    """
    from app.logging_config import setup_logging

    setup_logging()
    setup_logging()

    assert len(logging.getLogger().handlers) == 1