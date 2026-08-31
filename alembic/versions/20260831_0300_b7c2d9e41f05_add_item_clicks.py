"""add items.click_count + item_click_events

Revision ID: b7c2d9e41f05
Revises: a3f18c5d2b47
Create Date: 2026-08-31 03:00:00.000000+00:00

대문 "인기 물품" 레일을 위한 클릭 집계다.

- item_click_events: 클릭 한 건. (item_id, session_hash, bucket_start) 유니크로
  "한 세션이 한 매물을 30분에 한 번"만 남긴다. 중복 제거는 이 제약 하나가 맡는다.
- items.click_count: 위 테이블 건수의 캐시. 이벤트를 넣을 때 +1 한다. 대문이
  열릴 때마다 COUNT를 돌리지 않으려는 것이고, 어긋나면 이벤트 테이블이 진실이다.

기존 행은 전부 0에서 시작한다(server_default). 과거 클릭은 기록이 없으니 셀 수
없고, 그걸 지어내지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2d9e41f05"
down_revision: str | None = "a3f18c5d2b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("click_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(op.f("ix_items_click_count"), "items", ["click_count"], unique=False)

    op.create_table(
        "item_click_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name=op.f("fk_item_click_events_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_item_click_events")),
        sa.UniqueConstraint(
            "item_id",
            "session_hash",
            "bucket_start",
            name=op.f("uq_item_click_events_item_id_session_hash_bucket_start"),
        ),
    )
    op.create_index(
        op.f("ix_item_click_events_item_id"), "item_click_events", ["item_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_item_click_events_item_id"), table_name="item_click_events")
    op.drop_table("item_click_events")
    op.drop_index(op.f("ix_items_click_count"), table_name="items")
    op.drop_column("items", "click_count")
