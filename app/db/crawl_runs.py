# app/db/crawl_runs.py

"""
crawl_runs 테이블 접근 계층.

크롤러는 라운드를 시작할 때 기록을 만들고 끝날 때 갱신한다. 백엔드는 최신 기록을
읽어 /api/meta로 내려준다. 두 프로세스가 갈라져도 같은 곳을 보게 하는 것이 목적이다.

items 테이블과 파일을 나눈 이유는 성격이 달라서다. repository.py는 사용자가 조회하는
데이터를 다루고, 이쪽은 운영 상태를 다룬다. 나중에 크롤러만 별도 서비스로 떼어내면
이 파일만 따라가면 된다.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models import CrawlRun, CrawlRunStatus


def is_stale(run: CrawlRun, timeout_minutes: int) -> bool:
    """
    'running' 상태로 남아 있지만 실제로는 죽은 기록인지 판단한다.

    크롤러 프로세스가 SIGKILL이나 전원 차단으로 죽으면 finished_at을 못 남긴다.
    그 기록을 그대로 믿으면 /api/meta가 영원히 "수집 중"이라고 답하고,
    _should_crawl_now()는 영원히 다른 인스턴스가 돌고 있다고 착각한다.
    시작한 지 timeout_minutes가 지난 running 기록은 죽은 것으로 본다.
    """
    if run.status != CrawlRunStatus.RUNNING:
        return False

    started_at = run.started_at

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    return datetime.now(UTC) - started_at > timedelta(minutes=timeout_minutes)


async def start_run() -> int:
    """라운드 시작을 기록하고 id를 반환한다."""
    async with async_session() as session:
        run = CrawlRun(status=CrawlRunStatus.RUNNING)
        session.add(run)
        await session.commit()

        return run.id


async def finish_run(run_id: int, item_count: int, errors: list[str] | None = None) -> None:
    """
    라운드 성공을 기록한다.

    일부 작업만 실패한 경우도 성공으로 센다 — 당근이 막혔어도 중고나라 결과는
    들어왔으니 "수집이 아예 안 되는 상태"와는 구분해야 한다. 다만 실패 사실은
    error에 남겨서 밖에서 볼 수 있게 한다.
    """
    async with async_session() as session:
        run = await session.get(CrawlRun, run_id)

        if run is None:
            return

        run.status = CrawlRunStatus.SUCCESS
        run.finished_at = datetime.now(UTC)
        run.item_count = item_count
        run.error = " / ".join(errors) if errors else None

        await session.commit()


async def fail_run(run_id: int, error: str) -> None:
    """라운드 실패를 기록한다. item_count는 남기지 않는다."""
    async with async_session() as session:
        run = await session.get(CrawlRun, run_id)

        if run is None:
            return

        run.status = CrawlRunStatus.FAILED
        run.finished_at = datetime.now(UTC)
        run.error = error

        await session.commit()


async def get_latest_run(session=None) -> CrawlRun | None:
    """
    가장 최근에 시작된 라운드. 없으면 None.

    session을 넘기면 그걸 쓰고(요청 처리 중인 백엔드), 없으면 직접 만든다(크롤러).
    """
    stmt = select(CrawlRun).order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc()).limit(1)

    if session is not None:
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async with async_session() as own_session:
        result = await own_session.execute(stmt)
        return result.scalar_one_or_none()


async def count_successful_runs(session) -> int:
    """성공한 라운드 수. 0이면 아직 한 번도 성공하지 못했다는 뜻이다."""
    result = await session.execute(
        select(func.count())
        .select_from(CrawlRun)
        .where(CrawlRun.status == CrawlRunStatus.SUCCESS)
    )

    return result.scalar_one()