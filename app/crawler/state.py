# app/crawler/state.py

"""
크롤러의 현재 상태를 담는 모듈.

첫 크롤링을 백그라운드로 돌리면서 필요해졌다. 예전에는 서버가 열렸다는 것 자체가
"크롤링이 끝났다"는 신호였는데, 이제 서버는 바로 열리고 수집은 뒤에서 돈다. 그래서
지금 수집 중인지, 마지막 라운드가 언제 끝났는지, 실패했다면 왜인지를 밖에서 볼 수
있어야 한다. /api/meta가 이 값을 내려준다.

프로세스 안의 단일 인스턴스다. uvicorn을 워커 여러 개로 띄우면 워커마다 별도의
상태를 갖게 되고 각자 크롤링을 돌린다 — 그때는 크롤러를 앱에서 떼어내 별도
프로세스나 스케줄러(예: ECS 스케줄 태스크)로 옮겨야 한다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class CrawlerState:
    """크롤러가 지금 무엇을 하고 있는지."""

    is_running: bool = False
    started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_item_count: int | None = None
    last_error: str | None = None
    rounds_completed: int = 0

    def mark_started(self) -> None:
        self.is_running = True
        self.started_at = datetime.now(UTC)

    def mark_finished(self, item_count: int, errors: list[str] | None = None) -> None:
        """
        라운드 성공. 일부 작업이 실패했다면 errors에 담아 넘긴다.

        일부만 실패한 경우도 라운드 자체는 성공으로 센다 — 당근이 막혔어도 중고나라
        결과는 들어왔으니 "수집이 아예 안 되는 상태"와는 구분해야 한다. 다만 실패
        사실은 last_error에 남겨서 밖에서 볼 수 있게 한다.
        """
        self.is_running = False
        self.last_finished_at = datetime.now(UTC)
        self.last_item_count = item_count
        self.last_error = " / ".join(errors) if errors else None
        self.rounds_completed += 1

    def mark_failed(self, error: BaseException) -> None:
        """
        실패해도 rounds_completed는 올리지 않는다. 그래야 "한 번도 성공 못 했다"와
        "돌긴 도는데 이번에 실패했다"를 구분할 수 있다.
        """
        self.is_running = False
        self.last_finished_at = datetime.now(UTC)
        self.last_error = f"{type(error).__name__}: {error}"


# 앱 전체에서 공유하는 단일 상태.
crawler_state = CrawlerState()
