# app/tests/test_parse_health.py

"""
카드 파싱 성적 테스트.

이 기능의 목적은 관측이 아니라 **데이터 훼손 방지**다.

사이트가 DOM을 바꾸면 셀렉터는 카드를 찾는데 내용을 못 읽는다. 이때 크롤링은 예외
없이 끝나고 건수만 조용히 줄어든다. 문제는 그다음이다 — 못 읽은 매물을 "사라졌다"고
판단하면 DOM 변경 한 번에 멀쩡한 매물이 대량으로 비활성 처리된다.

그래서 실패율이 높으면 `complete=False`로 내려 미발견 판정에서 제외한다. 이 프로젝트가
일관되게 지키는 "안 보였다 ≠ 사라졌다"를 파싱 실패에도 적용한 것이다.
"""

import pytest

from app.domain.collection import Collection
from app.domain.parse_health import (
    FAILURE_RATE_THRESHOLD,
    MIN_SAMPLE_SIZE,
    ParseHealth,
)

# ---------------------------------------------------------------------------
# 세는 규칙
# ---------------------------------------------------------------------------


def test_counts_failures():
    health = ParseHealth(seen=60, attempted=50, parsed=45)

    assert health.failed == 5
    assert health.failure_rate == pytest.approx(0.1)


def test_seen_is_not_attempted():
    """
    검색 결과에는 "판매하기" 버튼처럼 매물이 아닌 링크가 섞인다. 이런 걸 실패로
    세면 실패율이 늘 높게 나와 진짜 문제를 못 알아본다.
    """
    health = ParseHealth(seen=60, attempted=50, parsed=50)

    assert health.failed == 0
    assert health.is_degraded is False


def test_no_attempts_is_not_a_failure():
    """검색 결과가 비어 있는 경우. 0으로 나누면 안 된다."""
    health = ParseHealth()

    assert health.failure_rate == 0.0
    assert health.is_degraded is False


# ---------------------------------------------------------------------------
# 판정 기준
# ---------------------------------------------------------------------------


def test_high_failure_rate_is_degraded():
    health = ParseHealth(seen=60, attempted=50, parsed=10)

    assert health.failure_rate == pytest.approx(0.8)
    assert health.is_degraded is True


def test_small_sample_is_not_judged():
    """
    2개 중 1개가 실패했다고 "실패율 50%"라 경고하면 로그가 시끄러워지고, 정작
    중요한 경고를 놓친다.
    """
    health = ParseHealth(seen=3, attempted=2, parsed=1)

    assert health.failure_rate == pytest.approx(0.5)
    assert health.is_degraded is False, "표본이 적으면 판단하지 않아야 한다"


def test_threshold_boundary():
    """
    일부 카드가 형식에서 벗어나는 것은 정상이다(광고, 삭제 중인 매물).
    임계값 미만은 통과해야 한다.
    """
    just_under = ParseHealth(attempted=100, parsed=71)  # 29% 실패
    just_over = ParseHealth(attempted=100, parsed=70)  # 30% 실패

    assert just_under.failure_rate < FAILURE_RATE_THRESHOLD
    assert just_under.is_degraded is False
    assert just_over.is_degraded is True


def test_minimum_sample_boundary():
    """경계에서 정확히 켜지는지."""
    below = ParseHealth(attempted=MIN_SAMPLE_SIZE - 1, parsed=0)
    at = ParseHealth(attempted=MIN_SAMPLE_SIZE, parsed=0)

    assert below.is_degraded is False
    assert at.is_degraded is True


# ---------------------------------------------------------------------------
# 합치기
# ---------------------------------------------------------------------------


def test_merge_accumulates():
    """중고나라는 페이지마다 세므로 브랜드 단위로 합쳐야 한다."""
    total = ParseHealth(seen=50, attempted=50, parsed=50)
    total.merge(ParseHealth(seen=50, attempted=50, parsed=20))

    assert total.attempted == 100
    assert total.parsed == 70
    assert total.failed == 30


def test_merge_can_reveal_a_problem():
    """
    페이지 하나에서 5건 실패는 흔하다. 세 페이지 내내 그러면 규칙이 안 맞는 것이다.
    """
    total = ParseHealth()

    for _ in range(3):
        total.merge(ParseHealth(attempted=50, parsed=30))

    assert total.is_degraded is True


# ---------------------------------------------------------------------------
# 완전성 전파 — 이 기능의 핵심
# ---------------------------------------------------------------------------


def test_degraded_parsing_marks_collection_incomplete():
    """
    이게 이번 작업의 이유다.

    45개를 못 읽었는데 "이 범위를 빠짐없이 봤다"고 보고하면, repository는 그 45개를
    사라진 매물로 착각한다. DOM 변경 한 번에 대량 오탐이 나는 것이다.
    """
    collection = Collection(
        items=[1, 2, 3],
        complete=True,
        health=ParseHealth(seen=60, attempted=50, parsed=5),
    )

    collection.apply_parse_health()

    assert collection.complete is False


def test_healthy_parsing_keeps_completeness():
    collection = Collection(
        items=[1, 2, 3],
        complete=True,
        health=ParseHealth(seen=60, attempted=50, parsed=50),
    )

    collection.apply_parse_health()

    assert collection.complete is True


def test_apply_never_restores_completeness():
    """
    파싱은 멀쩡해도 페이지 한계에 걸렸으면 여전히 불완전하다. 이 함수는 완전성을
    내리기만 하고 올리지 않는다.
    """
    collection = Collection(
        items=[1],
        complete=False,  # 페이지 한계 등 다른 이유로 이미 불완전
        health=ParseHealth(attempted=50, parsed=50),
    )

    collection.apply_parse_health()

    assert collection.complete is False


def test_extend_merges_health():
    a = Collection(items=[1], health=ParseHealth(attempted=50, parsed=50))
    a.extend(Collection(items=[2], health=ParseHealth(attempted=50, parsed=10)))

    assert a.health.attempted == 100
    assert a.health.parsed == 60


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------


def test_to_dict_omits_seen():
    """
    seen은 진단 로그에는 쓸모 있지만, 밖에서 보는 사람에게 "매물이 아닌 링크가
    몇 개였나"는 의미 없는 숫자다.
    """
    payload = ParseHealth(seen=60, attempted=50, parsed=45).to_dict()

    assert payload == {
        "attempted": 50,
        "parsed": 45,
        "failed": 5,
        "failure_rate": 0.1,
    }
    assert "seen" not in payload