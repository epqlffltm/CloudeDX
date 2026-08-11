# app/tests/test_crawl_runs.py

"""
app.db.crawl_runs 테스트.

이 테이블의 존재 이유는 크롤러와 백엔드가 별도 컨테이너로 갈라져도 상태를 공유하는
것이다. 그래서 "크롤러가 쓴 것을 백엔드가 읽는다"를 실제로 확인한다 — 여기서는
같은 프로세스지만, DB를 거쳐 오간다는 점이 같다.
"""

from datetime import UTC, datetime, timedelta

from app.db import crawl_runs
from app.db.models import CrawlRun, CrawlRunStatus


async def test_start_run_records_running(session):
    run_id = await crawl_runs.start_run()
    latest = await crawl_runs.get_latest_run(session)

    assert latest.id == run_id
    assert latest.status == CrawlRunStatus.RUNNING
    assert latest.finished_at is None
    assert latest.item_count is None


async def test_finish_run_records_success(session):
    run_id = await crawl_runs.start_run()
    await crawl_runs.finish_run(run_id, 655)

    session.expire_all()
    latest = await crawl_runs.get_latest_run(session)

    assert latest.status == CrawlRunStatus.SUCCESS
    assert latest.item_count == 655
    assert latest.error is None
    assert latest.finished_at is not None


async def test_partial_failure_is_still_success(session):
    """
    당근이 막혔어도 중고나라 결과는 들어왔으니 "수집이 아예 안 되는 상태"와는
    구분해야 한다. 다만 실패 사실은 남긴다.
    """
    run_id = await crawl_runs.start_run()
    await crawl_runs.finish_run(run_id, 475, errors=["crawl_daangn_once: 봇 감지"])

    session.expire_all()
    latest = await crawl_runs.get_latest_run(session)

    assert latest.status == CrawlRunStatus.SUCCESS
    assert latest.item_count == 475
    assert "봇 감지" in latest.error


async def test_fail_run_records_failure(session):
    run_id = await crawl_runs.start_run()
    await crawl_runs.fail_run(run_id, "RuntimeError: 모든 수집 작업이 실패했습니다")

    session.expire_all()
    latest = await crawl_runs.get_latest_run(session)

    assert latest.status == CrawlRunStatus.FAILED
    assert latest.item_count is None
    assert "RuntimeError" in latest.error


async def test_count_successful_runs_excludes_failures(session):
    """
    rounds_completed가 0이면 "아직 한 번도 성공하지 못했다"는 뜻이어야 한다.
    실패를 세면 그 구분이 사라진다.
    """
    for _ in range(2):
        run_id = await crawl_runs.start_run()
        await crawl_runs.finish_run(run_id, 100)

    failed_id = await crawl_runs.start_run()
    await crawl_runs.fail_run(failed_id, "실패")

    assert await crawl_runs.count_successful_runs(session) == 2


async def test_get_latest_run_returns_none_when_empty(session):
    assert await crawl_runs.get_latest_run(session) is None


def test_is_stale_detects_abandoned_run():
    """
    크롤러가 SIGKILL이나 전원 차단으로 죽으면 finished_at을 못 남긴다. 그 기록을
    그대로 믿으면 /api/meta가 영원히 "수집 중"이라 답하고, _should_crawl_now()는
    영원히 다른 인스턴스가 돌고 있다고 착각해 수집이 멈춘다.
    """
    old = CrawlRun(
        status=CrawlRunStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(hours=3),
    )
    fresh = CrawlRun(status=CrawlRunStatus.RUNNING, started_at=datetime.now(UTC))

    assert crawl_runs.is_stale(old, 60) is True
    assert crawl_runs.is_stale(fresh, 60) is False


def test_finished_run_is_never_stale():
    finished = CrawlRun(
        status=CrawlRunStatus.SUCCESS,
        started_at=datetime.now(UTC) - timedelta(days=1),
        finished_at=datetime.now(UTC) - timedelta(days=1),
    )

    assert crawl_runs.is_stale(finished, 60) is False


async def test_backend_sees_crawler_state(client, session):
    """
    이 테스트가 crawl_runs 테이블의 존재 이유다. 크롤러가 남긴 기록을 백엔드가
    /api/meta로 읽어야 한다.
    """
    run_id = await crawl_runs.start_run()

    body = (await client.get("/api/meta")).json()["crawler"]
    assert body["is_running"] is True
    assert body["stale"] is False

    await crawl_runs.finish_run(run_id, 655)

    body = (await client.get("/api/meta")).json()["crawler"]
    assert body["is_running"] is False
    assert body["last_item_count"] == 655
    assert body["rounds_completed"] == 1
    assert body["interval_minutes"] == 30

    
async def test_meta_marks_abandoned_run_as_stale(client, session, monkeypatch):
    """
    타임아웃을 0으로 두고 방금 시작한 기록에 기대면 경과 시간이 0에 가까워 판정이
    타이밍에 좌우된다. 시작 시각을 과거로 밀어 확정적으로 만든다.
    """
    monkeypatch.setattr("app.routers.meta.CRAWL_RUN_TIMEOUT_MINUTES", 60)

    run_id = await crawl_runs.start_run()

    # 크롤러가 두 시간 전에 시작해 놓고 죽은 상황을 재현한다.
    run = await session.get(CrawlRun, run_id)
    run.started_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()

    body = (await client.get("/api/meta")).json()["crawler"]

    assert body["stale"] is True
    assert body["is_running"] is False