# app/crawler/runner.py

"""
수집 라운드의 실행 규칙. **Playwright를 임포트하지 않는다.**

"언제 수집할지", "실패하면 어떻게 할지", "결과를 어떻게 기록할지"만 다룬다.
실제로 어느 사이트를 어떻게 긁는지는 모른다 — 그 부분은 호출자가 job 목록으로 넘긴다
(app/crawler/scheduler.py가 진짜 크롤러를, 테스트가 가짜 함수를 넘긴다).

이렇게 나눈 이유는 둘이다.

1. **테스트**. 브라우저 없이 실행 규칙만 검증할 수 있다. 실패 처리와 주기 판단이 이
   프로젝트에서 가장 복잡한 로직인데, Playwright에 묶여 있으면 CI에서 돌릴 수 없다
   (CI의 test 잡은 백엔드 이미지와 같은 구성으로, Playwright 없이 설치한다).
2. **경계**. 규칙과 수단이 한 파일에 있으면 규칙만 쓰고 싶어도 Chromium이 딸려 온다.

실패에 대한 방침:
    한 작업이 실패해도 나머지는 계속한다. 전부 실패하면 라운드를 실패로 처리한다 —
    그러지 않으면 "0건 수집 성공"으로 기록돼서, 사이트가 전부 막힌 상태와 정말 매물이
    없는 상태를 구분할 수 없다. 라운드가 실패해도 루프는 죽지 않는다. 봇 감지나 일시적인
    네트워크 문제로 한 번 실패했다고 수집을 영영 멈추면 안 되기 때문이다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.config import (
    CRAWL_INTERVAL_MINUTES,
    CRAWL_RETRY_MINUTES,
    CRAWL_RUN_TIMEOUT_MINUTES,
)
from app.db import crawl_runs
from app.db.models import CrawlRunStatus

logger = logging.getLogger(__name__)

CRAWL_INTERVAL_SECONDS = CRAWL_INTERVAL_MINUTES * 60
RETRY_DELAY_SECONDS = CRAWL_RETRY_MINUTES * 60

# 한 라운드에서 실행할 작업.
#
# (저장 건수, 브랜드별 파싱 성적)을 반환한다. 성적을 함께 받는 이유는 DOM 변경으로
# 파싱이 깨졌을 때 그 사실을 crawl_runs에 남기고 /api/meta로 드러내기 위해서다.
# 반환하지 않으면 "오늘은 매물이 적었다"와 구분할 수 없다.
CrawlJob = Callable[[], Awaitable[tuple[int, dict[str, dict]]]]

# 작업이 돌려주는 성적의 형태:
#   {"당근마켓": {"샤넬": {"attempted": 58, "parsed": 58, "failed": 0, ...}}}


async def run_crawl_round(jobs: tuple[CrawlJob, ...]) -> int:
    """
    작업들을 순서대로 한 바퀴 실행하고 저장한 총 건수를 반환한다.

    한 작업이 실패해도 나머지는 계속 진행하되, **전부 실패하면 예외를 올린다.**
    일부만 실패한 경우는 성공으로 세고 사유만 기록한다 — 당근이 막혔어도 중고나라
    결과는 들어왔으니 "수집이 아예 안 되는 상태"와는 구분해야 한다.
    """
    if not jobs:
        raise ValueError("실행할 수집 작업이 없습니다.")

    run_id = await crawl_runs.start_run()
    total = 0
    errors: list[str] = []
    parse_health: dict[str, dict] = {}

    try:
        for job in jobs:
            try:
                saved, health = await job()
                total += saved

                # 작업이 {수집처: {브랜드: 성적}} 형태로 준다. 같은 수집처를 다루는
                # 작업이 둘 이상일 수 있으므로 덮어쓰지 않고 브랜드 단위로 합친다 —
                # update()로 덮으면 먼저 온 브랜드의 성적이 사라진다.
                for source, brands in health.items():
                    parse_health.setdefault(source, {}).update(brands)
            except Exception as exc:
                errors.append(f"{job.__name__}: {exc}")
                logger.warning("%s 실패: %s", job.__name__, exc)

        if len(errors) == len(jobs):
            raise RuntimeError("모든 수집 작업이 실패했습니다 — " + " / ".join(errors))
    except BaseException as exc:
        # 취소(CancelledError)도 여기로 온다. 기록을 running으로 남겨두면 프로세스를
        # 껐다 켜도 "수집 중"으로 보이므로 반드시 정리한다.
        await crawl_runs.fail_run(run_id, f"{type(exc).__name__}: {exc}")
        raise

    await crawl_runs.finish_run(
        run_id, total, errors=errors, parse_health=parse_health or None
    )

    return total


async def seconds_until_next_crawl() -> float:
    """
    프로세스 기동 시 다음 수집까지 실제로 남은 초를 반환한다.

    예전 crawler_loop는 should_crawl_now()가 False이면 남은 시간이 1분이든 29분이든
    전체 CRAWL_INTERVAL_SECONDS를 다시 잤다. 30분 주기에서 마지막 수집 29분 뒤
    프로세스를 재시작하면 원래 1분 뒤 돌아야 할 라운드가 30분 뒤로 밀려, 실제 간격이
    거의 59분이 될 수 있었다.

    이 함수는 crawl_runs 기준으로 남은 시간을 그대로 반환해 재시작이 스케줄을
    뒤로 미루지 않게 한다. 0이면 즉시 실행한다.
    """
    latest = await crawl_runs.get_latest_run()

    if latest is None:
        logger.info("수집 기록이 없어 즉시 시작합니다.")
        return 0.0

    if latest.status == CrawlRunStatus.RUNNING:
        if not crawl_runs.is_stale(latest, CRAWL_RUN_TIMEOUT_MINUTES):
            # 다른 프로세스가 언제 끝날지는 알 수 없다. 기존 동작처럼 한 정상 주기
            # 뒤 다시 확인한다. 중복 수집을 피하는 쪽을 우선한다.
            logger.info("다른 프로세스가 수집 중이라 이번 차례는 건너뜁니다.")
            return float(CRAWL_INTERVAL_SECONDS)

        logger.warning(
            "%d분 넘게 running으로 남은 기록이 있습니다. 비정상 종료로 보고 새로 시작합니다.",
            CRAWL_RUN_TIMEOUT_MINUTES,
        )
        return 0.0

    reference = latest.finished_at or latest.started_at

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    elapsed = (datetime.now(UTC) - reference).total_seconds()

    if elapsed >= CRAWL_INTERVAL_SECONDS:
        logger.info("마지막 수집이 %s분 전이라 즉시 시작합니다.", int(elapsed // 60))
        return 0.0

    remaining = max(0.0, CRAWL_INTERVAL_SECONDS - elapsed)
    logger.info(
        "마지막 수집이 최근이라 건너뜁니다. 약 %s분 뒤 시작합니다.",
        max(1, int((remaining + 59) // 60)),
    )

    return remaining


async def should_crawl_now() -> bool:
    """
    프로세스가 뜨자마자 수집을 시작해야 하는지 판단한다.

    외부 호출부와 기존 테스트 호환을 위해 bool API는 유지하되, 실제 대기 시간 계산은
    seconds_until_next_crawl() 한 곳에서 한다.
    """
    return await seconds_until_next_crawl() <= 0


async def crawler_loop(jobs: tuple[CrawlJob, ...]) -> None:
    """
    주기적으로 수집하는 루프.

    첫 라운드는 crawl_runs 기준으로 실제 남은 시간만 기다린다. 라운드가 실패해도
    루프는 유지하고, 정상 주기보다 짧게 기다렸다가 다시 시도한다 — 봇 감지 같은
    일시적 문제라면 주기 전체를 버릴 이유가 없다.

    백엔드 프로세스가 이 루프를 create_task로 띄울 때는 서버 시작을 막지 않는다
    (app/main.py 참고). 크롤러를 별도 컨테이너로 띄울 때는 app/crawler/__main__.py가
    이 루프만 돌린다.
    """
    logger.info("백그라운드 수집 시작 (주기 %s분)", CRAWL_INTERVAL_MINUTES)

    initial_delay = await seconds_until_next_crawl()
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)

    while True:
        try:
            total = await run_crawl_round(jobs)
            logger.info(
                "라운드 완료: %d건. %d분 뒤 다시 수집합니다.",
                total,
                CRAWL_INTERVAL_MINUTES,
            )
            delay = CRAWL_INTERVAL_SECONDS
        except asyncio.CancelledError:
            # 프로세스 종료 신호. 조용히 빠져나간다.
            logger.info("수집 루프를 종료합니다.")
            raise
        except Exception as exc:
            logger.warning("라운드 전체 실패: %s", exc)
            logger.info("%s분 뒤 다시 시도합니다.", CRAWL_RETRY_MINUTES)
            delay = RETRY_DELAY_SECONDS

        await asyncio.sleep(delay)
