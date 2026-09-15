"""Add users, contents, and watchlist tables.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP_COLUMNS = (
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    ),
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        *TIMESTAMP_COLUMNS,
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        *TIMESTAMP_COLUMNS,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title", name="uq_contents_title"),
    )
    op.create_table(
        "user_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        *TIMESTAMP_COLUMNS,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_lists_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_user_lists_user_id_name"),
    )
    op.create_table(
        "user_list_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_list_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        *TIMESTAMP_COLUMNS,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_list_id"],
            ["user_lists.id"],
            name="fk_user_list_contents_user_list_id_user_lists",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["contents.id"],
            name="fk_user_list_contents_content_id_contents",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_list_id",
            "content_id",
            name="uq_user_list_contents_user_list_id_content_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_list_contents")
    op.drop_table("user_lists")
    op.drop_table("contents")
    op.drop_table("users")
