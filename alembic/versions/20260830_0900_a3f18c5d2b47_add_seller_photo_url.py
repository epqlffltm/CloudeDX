"""add sellers.photo_url

Revision ID: a3f18c5d2b47
Revises: e6b1a24d7c93
Create Date: 2026-08-30 09:00:00.000000+00:00

판매자 시트의 매장 사진(간판·가게 내부) 자리를 위한 컬럼이다.

처음에는 화면이 그 판매자의 첫 매물 사진을 대신 세웠는데, 가게 소개 칸에
파는 물건이 걸려 있는 셈이라 이상했다. 매장 사진은 판매자의 속성이므로
매물이 아니라 sellers 테이블에 둔다.

nullable이다 — 온라인 전용 판매자(has_store=false)는 찍을 매장이 없고,
사진을 아직 안 올린 판매자도 정상 상태다. 화면은 값이 없으면 사진 칸을
아예 그리지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f18c5d2b47"
down_revision: str | None = "e6b1a24d7c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sellers", sa.Column("photo_url", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("sellers", "photo_url")
