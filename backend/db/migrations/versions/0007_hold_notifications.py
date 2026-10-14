"""Persist deduplicated hold notifications.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "patron_id", sa.Integer(), sa.ForeignKey("patrons.id"), nullable=False
        ),
        sa.Column(
            "hold_id",
            sa.Integer(),
            sa.ForeignKey("item_holds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reservation_id", sa.Integer(), sa.ForeignKey("reservations.id")),
        sa.Column(
            "kind",
            sa.Enum("HOLD_EXPIRING", "HOLD_CONVERTED", name="notificationkind"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("hold_id", "kind", name="uq_notifications_hold_kind"),
    )
    op.create_index(
        "ix_item_holds_status_expires_at_id",
        "item_holds",
        ["status", "expires_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_item_holds_status_expires_at_id", table_name="item_holds")
    op.drop_table("notifications")
    sa.Enum(name="notificationkind").drop(op.get_bind(), checkfirst=True)
