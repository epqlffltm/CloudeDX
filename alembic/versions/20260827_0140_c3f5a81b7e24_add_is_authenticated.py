"""add is_authenticated to items

Revision ID: c3f5a81b7e24
Revises: bf68daafc680
Create Date: 2026-08-27 01:40:00.000000+00:00

정품 인증 뱃지 컬럼. 화면 카드의 "정품인증" 씰이 이 값 하나만 본다.

server_default='false'를 주는 이유는 기존 행 때문이다. NOT NULL 컬럼을 기본값 없이
추가하면 이미 들어 있는 매물에 채울 값이 없어 ALTER가 실패한다. 그리고 기본값이 곧
사실이기도 하다 — 지금까지 저장된 것은 크롤링분과, 인증 컬럼이 없던 시절의 업로드분이다.
어느 쪽도 증표를 확인한 적이 없으므로 false가 맞다.

**소급 UPDATE를 하지 않는다.** source='직접등록'인 기존 행을 true로 밀어 올리고 싶은
유혹이 있는데, 그러면 업자가 인증 표시를 하지 않은 물건까지 뱃지가 붙는다. 뱃지는
"업로드된 매물"이 아니라 "증표를 확인한 매물"을 뜻한다. 기존 업로드분은 업자가
인증 컬럼을 채워 다시 올리면 upsert가 갱신한다.

인덱스를 함께 만든다. authenticated_only 필터가 이 컬럼 단독 조건으로 걸린다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f5a81b7e24"
down_revision: str | None = "bf68daafc680"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "is_authenticated",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_items_is_authenticated"),
        "items",
        ["is_authenticated"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_items_is_authenticated"), table_name="items")
    op.drop_column("items", "is_authenticated")
