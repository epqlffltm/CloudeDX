# app/tests/test_review_regressions.py

"""
2026-09 코드 리뷰에서 발견된 교차 조건 버그 회귀 테스트.

기존 테스트가 각각의 기능은 잘 검증했지만, 다중 카테고리 확장 뒤 생긴
"같은 URL 재분류"와 "다른 category의 lifecycle 상태" 교차 조건은 빠져 있었다.
"""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select

from app.crawler import runner
from app.crawler.joongna.config import JoongnaCrawlerConfig
from app.db import crawl_runs, repository
from app.db.models import CrawlRun, ItemRecord
from app.domain.collection import CrawlScope
from app.domain.models import CrawledItem
from app.ratelimit import client_ip


def item(url: str, title: str) -> CrawledItem:
    return CrawledItem(
        source="중고나라",
        brand="샤넬",
        title=title,
        price="4,000,000원",
        price_value=4_000_000,
        region=None,
        time_text=None,
        image_url=None,
        url=url,
        is_sold=False,
    )


async def test_upsert_updates_category_when_same_url_is_reclassified(session):
    url = "https://example.com/reclassified"

    await repository.upsert_items([item(url, "샤넬 클래식 가방")])
    first = (
        await session.execute(select(ItemRecord).where(ItemRecord.url == url))
    ).scalar_one()
    assert first.category == "bag"

    await repository.upsert_items([item(url, "샤넬 J12 시계")])

    session.expire_all()
    updated = await session.get(ItemRecord, first.id)
    assert updated.category == "watch"


async def test_sweep_does_not_deactivate_another_category(session, monkeypatch):
    bag_url = "https://example.com/bag"
    watch_url = "https://example.com/watch"

    await repository.upsert_items(
        [
            item(bag_url, "샤넬 클래식 가방"),
            item(watch_url, "샤넬 J12 시계"),
        ]
    )

    watch_obj = (
        await session.execute(select(ItemRecord).where(ItemRecord.url == watch_url))
    ).scalar_one()
    # 다른 category가 이미 임계값에 걸려 있는 상태를 만들어 두면, 예전의 두 번째
    # UPDATE(category 조건 누락)는 이번 bag sweep에서 이 watch까지 비활성화했다.
    watch_obj.missing_count = 1
    await session.commit()

    monkeypatch.setattr(repository, "MISSING_THRESHOLD", 1)

    result = await repository.sweep_missing(
        CrawlScope(source="중고나라", brands=frozenset({"샤넬"}), category="bag"),
        seen_urls=set(),
    )

    session.expire_all()
    bag_obj = (
        await session.execute(select(ItemRecord).where(ItemRecord.url == bag_url))
    ).scalar_one()
    watch_obj = (
        await session.execute(select(ItemRecord).where(ItemRecord.url == watch_url))
    ).scalar_one()

    assert result["deactivated"] == 1
    assert bag_obj.is_active is False
    assert watch_obj.is_active is True


def test_client_ip_uses_normalized_request_client_not_raw_xff():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"203.0.113.99")],
            "client": ("10.0.0.25", 43210),
            "server": ("test", 80),
            "scheme": "http",
            "query_string": b"",
            "http_version": "1.1",
        }
    )

    assert client_ip(request) == "10.0.0.25"


async def test_restart_waits_only_remaining_crawl_interval(session, monkeypatch):
    monkeypatch.setattr(runner, "CRAWL_INTERVAL_SECONDS", 30 * 60)

    run_id = await crawl_runs.start_run()
    await crawl_runs.finish_run(run_id, 1)

    run = await session.get(CrawlRun, run_id)
    run.finished_at = datetime.now(UTC) - timedelta(minutes=29)
    await session.commit()

    remaining = await runner.seconds_until_next_crawl()

    assert 30 <= remaining <= 90


def test_joongna_default_url_does_not_force_old_bag_category():
    config = JoongnaCrawlerConfig(brand="롤렉스", keyword_suffix="시계")

    url = config.build_search_url(2)

    assert "page=2" in url
    assert "category=" not in url


def test_joongna_explicit_verified_category_is_still_supported():
    config = JoongnaCrawlerConfig(
        brand="샤넬",
        keyword_suffix="가방",
        category="verified-category-id",
    )

    assert "category=verified-category-id" in config.build_search_url(1)
