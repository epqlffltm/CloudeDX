"""add admin_memo single-row table

Revision ID: e6b1a24d7c93
Revises: d7e2b94c1f08
Create Date: 2026-08-29 10:30:00.000000+00:00

관리자 공용 메모를 파일에서 DB로 옮긴다.

이전 구현은 서버의 텍스트 파일 한 장(data/admin_memo.txt)이었다. 배포가
백엔드 여러 대 + 컨테이너로 확정되면서 성립하지 않게 됐다 — A 서버에 저장한
메모를 B 서버가 모르고, 컨테이너가 교체되면 파일째 사라진다. 모든 인스턴스가
이미 공유하는 저장소는 DB 하나이므로 한 줄짜리 테이블로 옮긴다.

행은 항상 id=1 하나다. CHECK(id = 1)로 스키마에 박는다 — 애플리케이션 버그로
두 번째 행이 들어가면 "어느 행이 진짜 메모인가"라는 답 없는 질문이 생긴다.

기존 파일의 내용은 옮기지 않는다. 이 마이그레이션이 도는 시점에 파일이 어느
서버에 있는지 DB가 알 수 없고, 메모는 아직 시연 전이라 잃을 내용도 없다.
필요하면 화면에서 한 번 붙여넣으면 된다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6b1a24d7c93"
down_revision: str | None = "d7e2b94c1f08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_memo",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_admin_memo_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_memo")),
    )


def downgrade() -> None:
    op.drop_table("admin_memo")
