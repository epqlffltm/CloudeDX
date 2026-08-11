# app/crawler/scheduler.py

"""
크롤링 자동화.

당근마켓/중고나라 모두 Playwright 기반 비동기 크롤러로 통일했기 때문에,
더 이상 asyncio.to_thread 없이 순서대로 await하면 된다.

브랜드(LUXURY_BRANDS)를 사이트당 하나씩 순서대로 검색해서 DB에 upsert한다.
브랜드 수만큼 검색 횟수가 늘어나므로 한 라운드 전체 소요 시간도 그만큼 길어진다
(현재 4개 브랜드 x 2개 사이트 = 검색 8회, 정상적인 네트워크 환경에서 수 분 단위 소요 예상).

이 루프는 서버 시작을 막지 않는다. main.py의 lifespan이 create_task로 띄우고 바로
요청을 받기 시작하므로, 수집이 도는 동안에도 게시판과 API는 정상 응답한다
(수집 전이면 빈 목록). 크롤러를 별도 프로세스로 띄울 때는 app/crawler/__main__.py가
이 루프만 돌린다.

진행 상황은 crawl_runs 테이블에 기록되고 /api/meta로 노출된다. 프로세스 메모리가
아니라 DB에 남기는 이유는 크롤러와 백엔드가 별도 컨테이너로 갈라질 수 있기 때문이다.

실패에 대한 방침:
    한 브랜드가 실패해도 나머지 브랜드는 계속하고, 한 사이트가 통째로 실패해도 다른
    사이트는 계속한다. 라운드 전체가 실패해도 루프는 죽지 않고 다음 주기를 기다린다 —
    봇 감지나 일시적인 네트워크 문제로 크롤링이 한 번 실패했다고 서버가 영영 수집을
    멈추면 안 되기 때문이다. 대신 실패 사실은 상태에 남겨 밖에서 볼 수 있게 한다.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import (
    CRAWL_INTERVAL_MINUTES,
    CRAWL_RETRY_MINUTES,
    CRAWL_RUN_TIMEOUT_MINUTES,
    JOONGNA_PAGES_PER_BRAND,
)
from app.crawler.base import save_json
from app.crawler.brands import LUXURY_BRANDS
from app.crawler.daangn.config import DaangnCrawlerConfig
from app.crawler.daangn.crawler import DaangnCrawler
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.crawler.joongna.crawler import JoongnaCrawler
from app.db import crawl_runs
from app.db.models import CrawlRunStatus
from app.db.repository import upsert_items

# 설정값은 app/config.py에서 가져온다. 백엔드(/api/meta)도 수집 주기를 알아야 하는데,
# 그 상수를 여기 두면 백엔드가 이 모듈을 임포트하게 되고 Playwright까지 딸려 온다.
CRAWL_INTERVAL_SECONDS = CRAWL_INTERVAL_MINUTES * 60
RETRY_DELAY_SECONDS = CRAWL_RETRY_MINUTES * 60


async def crawl_daangn_once() -> int:
    """당근마켓을 브랜드별로 한 바퀴 수집하고 저장한 건수를 반환한다."""
    print("[crawler] 당근마켓 자동 크롤링 시작")

    all_items = []

    for brand in LUXURY_BRANDS:
        crawler = DaangnCrawler(
            DaangnCrawlerConfig(
                brand=brand,
                headless=True,
                scroll_count=6,
            )
        )

        try:
            items = await crawler.crawl()
            all_items.extend(items)
            print(f"[crawler] 당근마켓 '{brand}' {len(items)}건")
        except Exception as exc:
            print(f"[crawler] 당근마켓 '{brand}' 크롤링 실패: {exc}")

    save_json(all_items, Path("data/crawled_items.json"))
    saved = await upsert_items(all_items)

    print(f"[crawler] 당근마켓 자동 크롤링 완료: 총 {saved}건")

    return saved


async def crawl_joongna_once() -> int:
    """중고나라를 브랜드별로 한 바퀴 수집하고 저장한 건수를 반환한다."""
    print("[crawler] 중고나라 자동 크롤링 시작")

    all_items = []

    for brand in LUXURY_BRANDS:
        crawler = JoongnaCrawler(
            JoongnaCrawlerConfig(
                brand=brand,
                headless=True,
                max_pages=JOONGNA_PAGES_PER_BRAND,
            )
        )

        try:
            items = await crawler.crawl()
            all_items.extend(items)
            print(f"[crawler] 중고나라 '{brand}' {len(items)}건")
        except Exception as exc:
            print(f"[crawler] 중고나라 '{brand}' 크롤링 실패: {exc}")

    save_json(all_items, Path("data/joongna_crawled_items.json"))
    saved = await upsert_items(all_items)

    print(f"[crawler] 중고나라 자동 크롤링 완료: 총 {saved}건")

    return saved


# 순서대로 실행할 크롤링 작업 목록. 사이트를 추가하고 싶으면 여기에 함수 하나만 더 넣으면 된다.
CRAWL_JOBS: tuple[Callable[[], Awaitable[int]], ...] = (
    crawl_daangn_once,
    crawl_joongna_once,
)


async def run_crawl_round() -> int:
    """
    등록된 크롤링 작업을 순서대로 한 바퀴 실행하고 저장한 총 건수를 반환한다.

    한 작업이 실패해도 나머지는 계속 진행한다. 다만 **전부 실패하면 예외를 올린다** —
    그러지 않으면 "0건 수집 성공"으로 기록돼서, 사이트가 전부 막힌 상태와 정말 매물이
    없는 상태를 구분할 수 없게 된다. 호출하는 루프는 이 예외를 보고 짧은 간격으로
    재시도한다.
    """
    run_id = await crawl_runs.start_run()
    total = 0
    errors: list[str] = []

    try:
        for job in CRAWL_JOBS:
            try:
                total += await job()
            except Exception as exc:
                errors.append(f"{job.__name__}: {exc}")
                print(f"[crawler] {job.__name__} 실패: {exc}")

        if errors and len(errors) == len(CRAWL_JOBS):
            raise RuntimeError("모든 수집 작업이 실패했습니다 — " + " / ".join(errors))
    except BaseException as exc:
        # 취소(CancelledError)도 여기로 온다. 기록을 running으로 남겨두면 프로세스를
        # 껐다 켜도 "수집 중"으로 보이므로 반드시 정리한다.
        await crawl_runs.fail_run(run_id, f"{type(exc).__name__}: {exc}")
        raise

    await crawl_runs.finish_run(run_id, total, errors=errors)

    return total


async def _should_crawl_now() -> bool:
    """
    프로세스가 뜨자마자 수집을 시작해야 하는지 판단한다.

    개발 중에는 서버를 하루에도 몇 번씩 재시작하는데, 그때마다 8회 검색을 새로 도는 건
    사이트에도 부담이고 봇 감지 위험도 올린다. 마지막 라운드가 주기 안에 있으면
    건너뛰고 다음 주기를 기다린다. 기록이 없으면(첫 실행) 당연히 바로 시작한다.

    items.last_seen_at이 아니라 crawl_runs를 보는 이유는 실패한 라운드도 세기 위해서다.
    전부 실패한 라운드는 아무것도 저장하지 않으므로 last_seen_at이 갱신되지 않고,
    그러면 재시작할 때마다 곧바로 다시 긁으러 간다.

    다른 프로세스가 수집 중이면 양보한다. 크롤러 컨테이너가 배포 중에 잠깐 두 개가 되는
    상황에서 같은 매물을 두 번 긁는 걸 줄여준다. 다만 이건 진짜 잠금이 아니다 —
    두 프로세스가 동시에 확인하면 둘 다 통과할 수 있다. 완전한 상호 배제가 필요해지면
    Postgres 어드바이저리 락으로 올려야 한다.
    """
    latest = await crawl_runs.get_latest_run()

    if latest is None:
        print("[crawler] 수집 기록이 없어 즉시 시작합니다.")
        return True

    if latest.status == CrawlRunStatus.RUNNING:
        if not crawl_runs.is_stale(latest, CRAWL_RUN_TIMEOUT_MINUTES):
            print("[crawler] 다른 프로세스가 수집 중이라 이번 차례는 건너뜁니다.")
            return False

        print(
            f"[crawler] {CRAWL_RUN_TIMEOUT_MINUTES}분 넘게 running으로 남은 기록이 있습니다. "
            "비정상 종료로 보고 새로 시작합니다."
        )
        return True

    reference = latest.finished_at or latest.started_at

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    elapsed = (datetime.now(UTC) - reference).total_seconds()

    if elapsed >= CRAWL_INTERVAL_SECONDS:
        print(f"[crawler] 마지막 수집이 {int(elapsed // 60)}분 전이라 즉시 시작합니다.")
        return True

    remaining = int((CRAWL_INTERVAL_SECONDS - elapsed) // 60)
    print(f"[crawler] 마지막 수집이 최근이라 건너뜁니다. 약 {remaining}분 뒤 시작합니다.")

    return False


async def crawler_loop() -> None:
    """
    백그라운드에서 주기적으로 수집하는 루프.

    main.py의 lifespan이 create_task로 띄우기 때문에 서버 시작을 막지 않는다.
    첫 라운드는 _should_crawl_now()가 판단해서 즉시 돌거나 다음 주기까지 기다린다.

    라운드가 실패해도 루프는 유지한다. 실패 후에는 정상 주기보다 짧게 기다렸다가
    다시 시도한다 — 봇 감지 같은 일시적 문제라면 30분을 통째로 버릴 이유가 없다.
    """
    print(f"[crawler] 백그라운드 수집 시작 (주기 {CRAWL_INTERVAL_MINUTES}분)")

    if not await _should_crawl_now():
        await asyncio.sleep(CRAWL_INTERVAL_SECONDS)

    while True:
        try:
            total = await run_crawl_round()
            print(f"[crawler] 라운드 완료: {total}건. {CRAWL_INTERVAL_MINUTES}분 뒤 다시 수집합니다.")
            delay = CRAWL_INTERVAL_SECONDS
        except asyncio.CancelledError:
            # 서버 종료. 조용히 빠져나간다.
            print("[crawler] 수집 루프를 종료합니다.")
            raise
        except Exception as exc:
            print(f"[crawler] 라운드 전체 실패: {exc}")
            print(f"[crawler] {RETRY_DELAY_SECONDS // 60}분 뒤 다시 시도합니다.")
            delay = RETRY_DELAY_SECONDS

        await asyncio.sleep(delay)