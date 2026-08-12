# app/tests/test_runner.py

"""
app.crawler.runner 테스트.

수집 라운드의 실행 규칙 — 실패 처리, 주기 판단, 기록 — 을 검증한다. 이 프로젝트에서
가장 분기가 많은 로직인데, 예전에는 Playwright에 묶여 있어 CI에서 돌릴 수 없었다.
사이트별 크롤러를 주입받는 구조로 바꾸면서 가짜 작업만으로 검증할 수 있게 됐다.

여기서 브라우저를 전혀 쓰지 않는다는 점이 중요하다. CI의 test 잡은 백엔드 이미지와
같은 구성(Playwright 없음)으로 도는데, 이 파일이 app.crawler.scheduler를 임포트하면
그 자리에서 실패한다. 아래는 runner만 임포트한다.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.crawler import runner
from app.db import crawl_runs
from app.db.models import CrawlRun, CrawlRunStatus


async def succeed(count: int = 7):
    """지정한 건수를 저장한 것처럼 행동하는 가짜 작업."""

    async def job() -> int:
        return count

    job.__name__ = f"succeed_{count}"
    return job


async def make_failing(message: str = "봇 감지"):
    async def job() -> int:
        raise RuntimeError(message)

    job.__name__ = "failing_job"
    return job


# ---------------------------------------------------------------------------
# run_crawl_round
# ---------------------------------------------------------------------------


async def test_round_sums_saved_counts(session):
    total = await runner.run_crawl_round((await succeed(3), await succeed(4)))

    assert total == 7

    latest = await crawl_runs.get_latest_run(session)
    assert latest.status == CrawlRunStatus.SUCCESS
    assert latest.item_count == 7
    assert latest.error is None


async def test_partial_failure_still_succeeds(session):
    """
    당근이 막혔어도 중고나라 결과는 들어왔으니 "수집이 아예 안 되는 상태"와 구분해야
    한다. 성공으로 세되 사유는 남긴다.
    """
    total = await runner.run_crawl_round((await succeed(5), await make_failing()))

    assert total == 5

    latest = await crawl_runs.get_latest_run(session)
    assert latest.status == CrawlRunStatus.SUCCESS
    assert latest.item_count == 5
    assert "봇 감지" in latest.error


async def test_total_failure_raises_and_records(session):
    """
    전부 실패했는데 성공으로 기록하면 "0건 수집 성공"이 되어, 사이트가 전부 막힌
    상태와 정말 매물이 없는 상태를 구분할 수 없게 된다.
    """
    with pytest.raises(RuntimeError, match="모든 수집 작업이 실패"):
        await runner.run_crawl_round((await make_failing(), await make_failing()))

    latest = await crawl_runs.get_latest_run(session)
    assert latest.status == CrawlRunStatus.FAILED
    assert latest.item_count is None


async def test_cancellation_does_not_leave_running_record(session):
    """
    기록을 running으로 남겨두면 프로세스를 껐다 켜도 /api/meta가 "수집 중"이라 답하고,
    should_crawl_now()는 다른 인스턴스가 돌고 있다고 착각해 수집이 멈춘다.
    """

    async def cancelled_job() -> int:
        raise asyncio.CancelledError

    cancelled_job.__name__ = "cancelled_job"

    with pytest.raises(asyncio.CancelledError):
        await runner.run_crawl_round((cancelled_job,))

    latest = await crawl_runs.get_latest_run(session)
    assert latest.status == CrawlRunStatus.FAILED
    assert latest.finished_at is not None


async def test_empty_jobs_rejected(session):
    """작업이 하나도 없으면 라운드 기록조차 남기지 않는다."""
    with pytest.raises(ValueError):
        await runner.run_crawl_round(())

    assert await crawl_runs.get_latest_run(session) is None


# ---------------------------------------------------------------------------
# should_crawl_now
# ---------------------------------------------------------------------------


async def test_starts_when_no_history(session):
    assert await runner.should_crawl_now() is True


async def test_skips_right_after_a_round(session):
    run_id = await crawl_runs.start_run()
    await crawl_runs.finish_run(run_id, 100)

    assert await runner.should_crawl_now() is False


async def test_starts_when_interval_has_passed(session, monkeypatch):
    run_id = await crawl_runs.start_run()
    await crawl_runs.finish_run(run_id, 100)

    # 주기를 0으로 두면 경계에 걸려 타이밍에 좌우되므로, 끝난 시각을 과거로 민다.
    run = await session.get(CrawlRun, run_id)
    run.finished_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()

    assert await runner.should_crawl_now() is True


async def test_yields_to_another_running_process(session):
    """
    배포 중에 크롤러 컨테이너가 잠깐 두 개가 되는 상황에서 중복 수집을 줄인다.
    (진짜 잠금은 아니다 — 동시에 확인하면 둘 다 통과할 수 있다.)
    """
    await crawl_runs.start_run()

    assert await runner.should_crawl_now() is False


async def test_takes_over_a_stale_running_record(session, monkeypatch):
    """
    크롤러가 강제 종료되면 finished_at을 못 남긴다. 그 기록을 그대로 믿으면 수집이
    영영 멈추므로, 오래된 running은 죽은 것으로 보고 새로 시작한다.
    """
    monkeypatch.setattr(runner, "CRAWL_RUN_TIMEOUT_MINUTES", 60)

    run_id = await crawl_runs.start_run()
    run = await session.get(CrawlRun, run_id)
    run.started_at = datetime.now(UTC) - timedelta(hours=3)
    await session.commit()

    assert await runner.should_crawl_now() is True


async def test_failed_round_still_counts_toward_interval(session):
    """
    전부 실패한 라운드는 아무것도 저장하지 않는다. items.last_seen_at을 기준으로 삼으면
    재시작할 때마다 곧바로 다시 긁으러 가는데, 봇 감지로 막힌 상황이라면 그게 제일
    안 좋은 행동이다. crawl_runs를 보므로 실패한 라운드도 주기에 반영된다.
    """
    with pytest.raises(RuntimeError):
        await runner.run_crawl_round((await make_failing(),))

    assert await runner.should_crawl_now() is False


# ---------------------------------------------------------------------------
# crawler_loop
# ---------------------------------------------------------------------------


async def test_loop_survives_repeated_failures(session, monkeypatch):
    """
    봇 감지나 일시적인 네트워크 문제로 한 번 실패했다고 수집을 영영 멈추면 안 된다.
    """
    monkeypatch.setattr(runner, "CRAWL_INTERVAL_SECONDS", 30)
    monkeypatch.setattr(runner, "RETRY_DELAY_SECONDS", 0.01)

    attempts = 0

    async def flaky() -> int:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("네트워크 끊김")

    flaky.__name__ = "flaky"

    task = asyncio.create_task(runner.crawler_loop((flaky,)))
    await asyncio.sleep(0.1)
    still_running = not task.done()

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert still_running, "루프가 실패를 만나 죽었다"
    assert attempts > 1, "재시도하지 않았다"


async def test_loop_retries_sooner_than_normal_interval(monkeypatch, session):
    """
    실패 후 대기는 정상 주기보다 짧아야 한다. 일시적 문제로 주기 전체를 버릴 이유가 없다.
    """
    assert runner.RETRY_DELAY_SECONDS < runner.CRAWL_INTERVAL_SECONDS


async def test_loop_waits_when_recent_round_exists(session, monkeypatch):
    """마지막 수집이 최근이면 첫 라운드를 곧바로 돌지 않는다."""
    monkeypatch.setattr(runner, "CRAWL_INTERVAL_SECONDS", 30)

    run_id = await crawl_runs.start_run()
    await crawl_runs.finish_run(run_id, 100)

    started = False

    async def job() -> int:
        nonlocal started
        started = True
        return 1

    job.__name__ = "job"

    task = asyncio.create_task(runner.crawler_loop((job,)))
    await asyncio.sleep(0.1)

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert started is False