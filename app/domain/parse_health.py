# app/domain/parse_health.py

"""
카드 파싱이 얼마나 성공했는지.

사이트가 DOM을 바꾸면 셀렉터는 카드를 찾는데 내용을 못 읽는 상황이 생긴다. 이때
크롤링은 예외 없이 끝나고 건수만 조용히 줄어든다. 500개 중 480개가 실패해도
"오늘은 매물이 적네"로 보인다.

그래서 세 가지를 함께 한다.

1. **측정** — 시도 대비 성공 건수를 센다.
2. **경고** — 실패율이 높으면 로그와 crawl_runs에 남긴다.
3. **완전성 판단에 반영** — 이게 핵심이다.

세 번째를 빼면 metric이 관측용으로만 남는다. 45개를 못 읽었는데 "이 범위를
빠짐없이 봤다"고 보고하면, repository는 그 45개를 **사라진 매물로 착각한다**.
DOM 변경 한 번에 멀쩡한 매물이 대량으로 비활성 처리되는 것이다.

이 프로젝트가 일관되게 지키는 원칙 — "안 보였다 ≠ 사라졌다" — 을 파싱 실패에도
적용한 것이다.

## 세는 기준

    seen       셀렉터에 걸린 카드 수
    attempted  실제로 파서에 넘긴 수 (유효 URL + 비어 있지 않은 텍스트)
    parsed     파서가 결과를 돌려준 수
    failed     attempted - parsed

**attempted를 seen과 나눈 이유**가 중요하다. 검색 결과 페이지에는 "판매하기"
버튼처럼 매물이 아닌 링크가 섞여 있다. 이런 걸 실패로 세면 실패율이 늘 높게 나와
진짜 문제를 못 알아본다.
"""

from dataclasses import dataclass

# 실패율이 이 값을 넘으면 파싱이 깨진 것으로 본다.
#
# 일부 카드가 형식에서 벗어나는 것은 정상이다(광고, 삭제 중인 매물). 다만 셋 중
# 하나가 실패한다면 그건 개별 예외가 아니라 규칙이 안 맞는 것이다.
FAILURE_RATE_THRESHOLD = 0.30

# 이 미만이면 비율을 판단하지 않는다.
#
# 2개 중 1개가 실패했다고 "실패율 50%"라고 경고하면 로그가 시끄러워지고, 정작
# 중요한 경고를 놓치게 된다.
MIN_SAMPLE_SIZE = 10


@dataclass(slots=True)
class ParseHealth:
    """한 범위(수집처 × 브랜드)의 파싱 성적."""

    seen: int = 0
    attempted: int = 0
    parsed: int = 0

    @property
    def failed(self) -> int:
        return self.attempted - self.parsed

    @property
    def failure_rate(self) -> float:
        """실패 비율(0.0~1.0). 시도가 없으면 0."""
        return self.failed / self.attempted if self.attempted else 0.0

    @property
    def is_degraded(self) -> bool:
        """
        파싱이 깨진 것으로 볼 만한지.

        표본이 적으면 판단하지 않는다. 우연히 몇 개 실패한 것과 규칙이 안 맞는
        것을 구분하려면 최소한의 건수가 필요하다.
        """
        return (
            self.attempted >= MIN_SAMPLE_SIZE
            and self.failure_rate >= FAILURE_RATE_THRESHOLD
        )

    def merge(self, other: "ParseHealth") -> None:
        """다른 범위의 성적을 합친다."""
        self.seen += other.seen
        self.attempted += other.attempted
        self.parsed += other.parsed

    def to_dict(self) -> dict[str, int | float]:
        """
        API·DB에 실을 형태.

        seen은 넣지 않는다. 진단 로그에는 쓸모 있지만, 밖에서 보는 사람에게는
        "매물이 아닌 링크가 몇 개였나"가 의미 없는 숫자다.
        """
        return {
            "attempted": self.attempted,
            "parsed": self.parsed,
            "failed": self.failed,
            "failure_rate": round(self.failure_rate, 3),
        }