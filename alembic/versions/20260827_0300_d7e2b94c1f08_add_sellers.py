"""add sellers table and items.seller_id

Revision ID: d7e2b94c1f08
Revises: c3f5a81b7e24
Create Date: 2026-08-27 03:00:00.000000+00:00

입점 판매자 테이블과, 매물에서 그것을 가리키는 외래키를 추가한다.

items.seller_id는 nullable이다. 기존 행이 전부 크롤링분이라 채울 값이 없고,
NULL이 곧 "우리 판매자가 아니다"라는 사실이기도 하다.

ondelete는 SET NULL이다. 판매자를 지운다고 매물까지 사라지면 이미 목록에 노출되고
검색에 걸린 매물이 통째로 증발한다. 매물은 남기고 연결만 끊는다.

business_number에 유니크를 건다. 같은 사업자가 두 번 등록되면 매물이 두 판매자로
갈라져, 화면에서 같은 가게가 서로 다른 연락처로 두 번 뜬다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e2b94c1f08"
down_revision: str | None = "c3f5a81b7e24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sellers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("business_number", sa.String(length=20), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("has_store", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("address", sa.String(length=200), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sellers")),
        sa.UniqueConstraint("business_number", name=op.f("uq_sellers_business_number")),
    )

    op.add_column("items", sa.Column("seller_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_items_seller_id"), "items", ["seller_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_items_seller_id_sellers"),
        "items",
        "sellers",
        ["seller_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_items_seller_id_sellers"), "items", type_="foreignkey")
    op.drop_index(op.f("ix_items_seller_id"), table_name="items")
    op.drop_column("items", "seller_id")
    op.drop_table("sellers")
