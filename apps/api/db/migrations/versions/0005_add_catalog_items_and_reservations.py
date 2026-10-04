"""Add catalog items, patrons, reservations, holds, and waitlist records.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column(
            "item_type",
            sa.Enum("DEVICE", "BOOK", "MOVIE", name="catalogitemtype"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity >= 0", name="ck_catalog_items_quantity_nonnegative"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "name",
            "category",
            "item_type",
            name="uq_catalog_items__name_category_item_type",
        ),
    )
    op.create_table(
        "patrons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "item_holds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("catalog_item_id", sa.Integer(), nullable=False),
        sa.Column("patron_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("CONFIRMED", "CANCELLED", "EXPIRED", name="holdstatus"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            name="fk_item_holds__catalog_item_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["patron_id"], ["patrons.id"], name="fk_item_holds__patron_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_item_holds__catalog_item_id_patron_id_status",
        "item_holds",
        ["catalog_item_id", "patron_id", "status"],
        unique=True,
        postgresql_where=sa.text("status = 'CONFIRMED'"),
        sqlite_where=sa.text("status = 'CONFIRMED'"),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("catalog_item_id", sa.Integer(), nullable=False),
        sa.Column("patron_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.Enum("CONFIRMED", "CANCELLED", name="status"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            name="fk_reservations__catalog_item_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["patron_id"], ["patrons.id"], name="fk_reservations__patron_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_reservations__catalog_item_id_patron_id_status",
        "reservations",
        ["catalog_item_id", "patron_id", "status"],
        unique=True,
        postgresql_where=sa.text("status = 'CONFIRMED'"),
        sqlite_where=sa.text("status = 'CONFIRMED'"),
    )
    op.create_table(
        "wait_list_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("catalog_item_id", sa.Integer(), nullable=False),
        sa.Column("patron_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            name="fk_wait_list_records__catalog_item_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["patron_id"], ["patrons.id"], name="fk_wait_list_records__patron_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_wait_list_records__catalog_item_id_patron_id_is_active",
        "wait_list_records",
        ["catalog_item_id", "patron_id", "is_active"],
        unique=True,
        postgresql_where=sa.text("is_active IS true"),
        sqlite_where=sa.text("is_active IS 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_wait_list_records__catalog_item_id_patron_id_is_active",
        table_name="wait_list_records",
        postgresql_where=sa.text("is_active IS true"),
        sqlite_where=sa.text("is_active IS 1"),
    )
    op.drop_table("wait_list_records")
    op.drop_index(
        "uq_reservations__catalog_item_id_patron_id_status",
        table_name="reservations",
        postgresql_where=sa.text("status = 'CONFIRMED'"),
        sqlite_where=sa.text("status = 'CONFIRMED'"),
    )
    op.drop_table("reservations")
    op.drop_index(
        "uq_item_holds__catalog_item_id_patron_id_status",
        table_name="item_holds",
        postgresql_where=sa.text("status = 'CONFIRMED'"),
        sqlite_where=sa.text("status = 'CONFIRMED'"),
    )
    op.drop_table("item_holds")
    op.drop_table("patrons")
    op.drop_table("catalog_items")
    for enum_name in ("holdstatus", "status", "catalogitemtype"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
