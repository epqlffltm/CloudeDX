"""add live_search_runs

Revision ID: c4a71f2e8b90
Revises: b7c2d9e41f05
Create Date: 2026-08-31 18:00:00.000000+00:00

실시간 검색(/api/live/search)의 쿨다운 저장소다.

검색어의 정규형(LiveQuery.search_key)마다 "마지막으로 시도한 시각"을 한 행씩 남긴다.
이 표가 생기면서 라우터의 어드바이저리 락이 사라졌다 — 쿨다운이 동시 호출까지 함께
막기 때문이다(app/db/live_runs.py 설명 참고).

기존 행이 없는 새 표라 데이터 이관이 없다. 비어 있는 상태에서는 모든 검색어가 첫
시도로 취급되어 통과한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a71f2e8b90"
down_revision: str | None = "b7c2d9e41f05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_search_runs",
        sa.Column("search_key", sa.String(length=120), nullable=False),
        sa.Column("last_keyword", sa.String(length=200), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("search_key", name=op.f("pk_live_search_runs")),
    )


def downgrade() -> None:
    op.drop_table("live_search_runs")
