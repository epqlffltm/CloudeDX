# app/logging_config.py

"""
로깅 설정.

`print()`를 쓰다가 옮겼다. 컨테이너 로그는 CloudWatch 같은 수집기로 흘러가는데,
`print()`에는 시각도 심각도도 없어서 "언제 무슨 일이 있었나"를 되짚을 수 없다.
알람을 걸 때도 ERROR만 골라낼 방법이 없다.

설정은 프로세스 진입점에서 딱 한 번 부른다(`app/main.py`, `app/crawler/__main__.py`).
라이브러리 코드는 `logging.getLogger(__name__)`으로 로거만 얻어 쓰고 설정은 건드리지
않는다 — 임포트하는 쪽이 출력 형태를 결정할 수 있어야 하기 때문이다.

LOG_FORMAT=json 으로 두면 한 줄 JSON으로 찍는다. CloudWatch Logs Insights나 Loki가
필드 단위로 질의할 수 있어서, 배포 환경에서는 이쪽이 낫다. 로컬에서는 사람이 읽는
text가 기본이다.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from app.config import LOG_FORMAT, LOG_LEVEL


class JsonFormatter(logging.Formatter):
    """로그 한 줄을 JSON 객체로 만든다."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # logger.info("...", extra={"brand": "샤넬"}) 로 넘긴 값을 함께 싣는다.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False)


# LogRecord가 기본으로 갖는 속성들. 이것들은 extra가 아니므로 JSON에 넣지 않는다.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


def setup_logging() -> None:
    """
    루트 로거를 설정한다. 프로세스 진입점에서 한 번만 호출한다.

    핸들러를 매번 새로 붙이지 않도록 기존 것을 비우고 시작한다. uvicorn이 자기
    핸들러를 먼저 붙이는 경우가 있어, 그대로 두면 같은 줄이 두 번 찍힌다.
    """
    handler = logging.StreamHandler(sys.stdout)

    if LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(LOG_LEVEL)

    # 접근 로그는 ALB/CloudFront에도 남고 양이 많아 기본은 WARNING으로 낮춘다.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # httpx는 요청마다 INFO를 찍는다. 테스트에서 특히 시끄럽고, 우리가 보내는 요청이
    # 아니라 받는 요청이 관심사라 낮춘다.
    logging.getLogger("httpx").setLevel(logging.WARNING)