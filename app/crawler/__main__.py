# app/crawler/__main__.py

"""
크롤러를 단독 프로세스로 실행하는 진입점.

    uv run python -m app.crawler            # 주기 루프 (상시 컨테이너)
    uv run python -m app.crawler --once     # 한 라운드만 돌고 종료 (스케줄 태스크)

백엔드(app/main.py)와 분리해서 돌리기 위한 것이다. 나누는 이유는 셋이다.

1. 이미지 크기 — Playwright와 Chromium이 1GB를 넘는다. 백엔드가 그걸 지고 다닐
   이유가 없다.
2. 스케일 — 백엔드를 2대로 늘리면 두 대가 각자 크롤링을 돌린다. 같은 매물을 두 번
   긁고 사이트에는 요청이 두 배로 간다.
3. 비용 — 크롤러는 30분에 한 번 몇 분만 일한다. 상시 프로세스 대신 스케줄 태스크로
   띄우면 유휴 시간에 브라우저를 안 올린다.

--once 가 필요한 이유:
    ECS 스케줄 태스크나 Kubernetes CronJob은 "실행하고 끝나는" 프로세스를 전제한다.
    스케줄러가 컨테이너를 띄우고, 프로세스가 종료 코드로 성패를 알리고, 다음 실행은
    다시 스케줄러가 띄운다. 상시 루프(crawler_loop)를 그런 환경에 넣으면 태스크가
    영원히 끝나지 않아 스케줄러가 다음 실행을 겹쳐 띄우거나 타임아웃으로 죽인다.

    종료 코드도 이때 의미를 갖는다. 실패를 0으로 끝내면 스케줄러는 성공으로 알고
    알람을 울리지 않는다. 아래에서 실패 시 1로 끝낸다.

백엔드에서 함께 돌리려면 ENABLE_CRAWLER=true로 두면 되고(로컬 개발 기본값),
분리 운영할 때는 백엔드 쪽을 false로 두고 이 진입점을 별도로 띄운다.
"""

import argparse
import asyncio
import logging
import sys

from app.crawler.runner import crawler_loop, run_crawl_round, should_crawl_now
from app.crawler.scheduler import CRAWL_JOBS
from app.db.engine import DATABASE_URL, mask_url, wait_for_db
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    # Playwright가 브라우저를 서브프로세스로 띄우려면 Proactor 루프가 필요하다.
    # Selector 계열 루프는 Windows에서 서브프로세스를 지원하지 않는다.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.crawler",
        description="당근마켓·중고나라 매물 수집기",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="한 라운드만 수집하고 종료한다 (ECS 스케줄 태스크 · CronJob 용)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "--once 와 함께 쓴다. 마지막 수집이 주기 안이어도 건너뛰지 않고 실행한다. "
            "수동으로 즉시 갱신할 때 쓴다."
        ),
    )

    return parser.parse_args()


async def run_once(*, force: bool) -> int:
    """
    한 라운드만 실행하고 종료 코드를 반환한다.

    force가 아니면 주기를 확인한다. 스케줄러가 실수로 촘촘히 띄우거나 재시도를
    걸었을 때 사이트를 연달아 두드리지 않게 하려는 것이다. 이 경우는 "할 일이
    없어서 끝난 것"이므로 성공(0)으로 본다.
    """
    if not force and not await should_crawl_now():
        logger.info("이번 실행은 건너뜁니다. (--force 로 무시할 수 있습니다)")
        return 0

    try:
        total = await run_crawl_round(CRAWL_JOBS)
    except Exception:
        # 스케줄러가 실패를 알아채려면 종료 코드가 0이 아니어야 한다.
        logger.exception("수집 라운드 실패")
        return 1

    logger.info("수집 완료: %d건", total)

    return 0


async def main() -> int:
    args = parse_args()

    logger.info("DB 연결 확인 중... (%s)", mask_url(DATABASE_URL))
    await wait_for_db()
    logger.info("DB 연결 확인 완료")

    if args.once:
        return await run_once(force=args.force)

    try:
        await crawler_loop(CRAWL_JOBS)
    except asyncio.CancelledError:
        # 컨테이너 종료 신호. 조용히 빠져나간다.
        pass

    return 0


if __name__ == "__main__":
    setup_logging()

    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("종료합니다.")
        sys.exit(130)