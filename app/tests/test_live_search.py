# app/tests/test_live_search.py

"""
실시간 검색(/api/live/search)의 쿨다운 테스트.

검증하려는 것은 응답 모양이 아니라 **번개장터에 실제로 몇 번 나갔는가**다. 그래서
크롤러를 가짜로 갈아끼우고 호출 횟수를 센다 — 상태 문자열만 보면 "cooldown 이라고
답하면서 뒤로는 조회하는" 구현도 통과해 버린다.

이 경로가 이 프로젝트에서 유일하게 사용자 입력이 그대로 남의 서버로 나가는 자리라,
"막힌다고 말한다"가 아니라 "안 나간다"를 확인해야 한다.
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import live_runs
from app.domain.collection import Collection
from app.routers import live as live_router


def install_fake_crawler(monkeypatch, *, fail: bool = False) -> list[str]:
    """
    번개장터 크롤러를 가짜로 바꾸고, 호출될 때마다 검색어를 담는 리스트를 돌려준다.

    fail=True 면 조회가 터진 상황을 흉내 낸다. 실패한 시도도 쿨다운에 계수되는지
    확인하기 위한 것이다 — 실패를 안 세면 안 되는 검색어를 가장 자주 두드리게 된다.
    """
    calls: list[str] = []

    class FakeCrawler:
        def __init__(self, config):
            self.config = config

        async def crawl(self):
            calls.append(self.config.keyword)

            if fail:
                raise RuntimeError("봇 감지")

            return Collection(items=[])

    monkeypatch.setattr(live_router, "BunjangCrawler", FakeCrawler)

    return calls


async def test_second_call_is_blocked_by_cooldown(client, monkeypatch):
    """같은 검색어를 연달아 치면 두 번째는 나가지 않는다."""
    calls = install_fake_crawler(monkeypatch)
    monkeypatch.setattr(live_router, "LIVE_SEARCH_COOLDOWN_SECONDS", 120)

    first = await client.get("/api/live/search", params={"q": "샤넬 클래식"})
    second = await client.get("/api/live/search", params={"q": "샤넬 클래식"})

    assert first.json()["status"] == "saved"
    assert second.json()["status"] == "cooldown"
    assert len(calls) == 1, "쿨다운 안의 두 번째 요청이 외부로 나갔다"


async def test_cooldown_folds_spelling_variants(client, monkeypatch):
    """
    표기가 달라도 같은 뜻이면 같은 쿨다운을 공유한다.

    별칭마다 키가 갈리면 "루이뷔통/루이비통"을 번갈아 치는 것만으로 쿨다운을
    빠져나갈 수 있다. 정규형(LiveQuery.search_key)을 키로 쓰는 이유가 이것이다.
    """
    calls = install_fake_crawler(monkeypatch)
    monkeypatch.setattr(live_router, "LIVE_SEARCH_COOLDOWN_SECONDS", 120)

    await client.get("/api/live/search", params={"q": "루이뷔통 가방"})
    second = await client.get("/api/live/search", params={"q": "루이비통 가방"})

    assert second.json()["status"] == "cooldown"
    assert len(calls) == 1


async def test_failed_attempt_still_counts(client, monkeypatch):
    """
    조회가 실패해도 시도로 계수한다.

    실패를 기록하지 않으면 사용자가 엔터를 연타하는 동안 실패한 검색어만 계속
    나간다 — 상대가 막고 있을 때 가장 세게 두드리는 셈이다.
    """
    calls = install_fake_crawler(monkeypatch, fail=True)
    monkeypatch.setattr(live_router, "LIVE_SEARCH_COOLDOWN_SECONDS", 120)

    first = await client.get("/api/live/search", params={"q": "구찌 마몬트"})
    second = await client.get("/api/live/search", params={"q": "구찌 마몬트"})

    assert first.json()["status"] == "failed"
    assert second.json()["status"] == "cooldown"
    assert len(calls) == 1


async def test_different_keywords_do_not_block_each_other(client, monkeypatch):
    """쿨다운은 검색어별이다. 한 사람의 검색이 다른 검색어를 막으면 안 된다."""
    calls = install_fake_crawler(monkeypatch)
    monkeypatch.setattr(live_router, "LIVE_SEARCH_COOLDOWN_SECONDS", 120)

    first = await client.get("/api/live/search", params={"q": "샤넬 클래식"})
    second = await client.get("/api/live/search", params={"q": "구찌 마몬트"})

    assert first.json()["status"] == "saved"
    assert second.json()["status"] == "saved"
    assert len(calls) == 2


async def test_zero_disables_cooldown(client, monkeypatch):
    """0은 끈다. 설정 계약이 SQL의 시간 비교가 아니라 코드 분기로 지켜지는지 본다."""
    calls = install_fake_crawler(monkeypatch)
    monkeypatch.setattr(live_router, "LIVE_SEARCH_COOLDOWN_SECONDS", 0)

    first = await client.get("/api/live/search", params={"q": "샤넬 클래식"})
    second = await client.get("/api/live/search", params={"q": "샤넬 클래식"})

    assert first.json()["status"] == "saved"
    assert second.json()["status"] == "saved"
    assert len(calls) == 2


async def test_overlong_query_is_ignored(client, monkeypatch):
    """
    아주 긴 검색어는 조회하지 않고 ignored 로 돌려준다.

    search_key 가 live_search_runs 의 기본키라, 길이를 막지 않으면 btree 인덱스 행
    상한을 넘겨 INSERT 자체가 터진다. 422 가 아니라 200 ignored 인 것은 이
    엔드포인트의 "실패해도 200" 계약 때문이다.
    """
    calls = install_fake_crawler(monkeypatch)

    response = await client.get("/api/live/search", params={"q": "샤넬 클래식 " * 20})

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert calls == []


async def test_attempt_is_committed_even_when_crawl_fails(client, monkeypatch, session):
    """
    시도 기록은 라우터 트랜잭션과 무관하게 남는다.

    쿨다운 기록을 크롤링과 같은 트랜잭션에 두면, 조회가 터져 롤백될 때 기록까지
    사라져 곧바로 재시도가 나간다. 그래서 선점 직후에 커밋한다.
    """
    install_fake_crawler(monkeypatch, fail=True)
    monkeypatch.setattr(live_router, "LIVE_SEARCH_COOLDOWN_SECONDS", 120)

    await client.get("/api/live/search", params={"q": "샤넬 클래식"})

    stored = (
        await session.execute(
            text("SELECT search_key, last_keyword FROM live_search_runs")
        )
    ).all()

    assert [row.search_key for row in stored] == ["샤넬bag"]
    assert stored[0].last_keyword == "샤넬 클래식"


async def test_concurrent_claims_let_exactly_one_through(session):
    """
    같은 검색어가 **같은 순간에** 들어와도 하나만 통과한다.

    라우터를 거치지 않고 선점 함수만 두 커넥션에서 동시에 부른다. 뒤엣것은 행
    잠금에서 기다렸다가 앞엣것이 커밋한 시각으로 조건을 다시 평가해 0행을 받는다 —
    "확인하고 나서 기록한다" 사이의 틈이 없다는 것이 이 문장의 핵심이다.
    """
    from app.db.engine import async_session

    async def claim() -> bool:
        async with async_session() as own:
            return await live_runs.claim_live_search(
                own, search_key="샤넬bag", keyword="샤넬 클래식", cooldown_seconds=120
            )

    results = await asyncio.gather(claim(), claim())

    assert sorted(results) == [False, True], f"동시 선점 결과가 {results} 였다"


async def test_claim_failure_does_not_leak_500(client, monkeypatch):
    """
    선점이 DB 장애로 터져도 200 failed 다.

    선점은 주 DB(writer)를 쓰는데 RDS 페일오버는 60~120초가 걸린다. 그동안 조회는
    읽기 복제본으로 멀쩡히 돌아가므로, 부가 기능 하나 때문에 500을 내보낼 이유가
    없다 — 이 엔드포인트의 계약은 "실패해도 200"이다.
    """
    calls = install_fake_crawler(monkeypatch)

    async def boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("writer failover"))

    monkeypatch.setattr(live_runs, "claim_live_search", boom)

    response = await client.get("/api/live/search", params={"q": "샤넬 클래식"})

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert calls == [], "쿨다운을 확인하지 못했는데 외부 조회가 나갔다"


async def test_claim_timeout_does_not_leak_500(client, monkeypatch):
    """
    선점이 제한시간을 넘겨도 매달리지 않고 200 failed 로 끝난다.

    asyncio.timeout 은 TimeoutError 를 올린다. 라우터가 SQLAlchemyError 만 잡고
    있으면 이 경로가 그대로 500이 된다.
    """
    calls = install_fake_crawler(monkeypatch)

    async def slow(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(live_runs, "claim_live_search", slow)

    response = await client.get("/api/live/search", params={"q": "샤넬 클래식"})

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert calls == []


@pytest.mark.parametrize("cooldown", [0, -1])
async def test_claim_skips_database_when_disabled(session, cooldown):
    """끈 상태에서는 DB를 왕복하지 않고 그대로 통과시킨다."""
    assert await live_runs.claim_live_search(
        session, search_key="샤넬bag", keyword="샤넬 클래식", cooldown_seconds=cooldown
    )

    rows = (await session.execute(text("SELECT count(*) FROM live_search_runs"))).scalar()

    assert rows == 0
