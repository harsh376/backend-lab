"""Add studios and associate titles with them.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "studios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_studios_name"),
    )
    op.add_column("titles", sa.Column("studio_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_titles_studio_id_studios",
        "titles",
        "studios",
        ["studio_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_titles_studio_id_studios", "titles", type_="foreignkey")
    op.drop_column("titles", "studio_id")
    op.drop_table("studios")
