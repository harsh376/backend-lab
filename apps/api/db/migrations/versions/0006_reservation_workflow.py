"""Align workflow statuses and link reservations to converted holds.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _statuses(upgrade: bool) -> None:
    """Replace enum types so newly added values are usable in this transaction."""
    postgres = op.get_bind().dialect.name == "postgresql"
    definitions = [
        (
            "item_holds",
            "holdstatus",
            ["WAITING", "ALLOCATED", "CONVERTED", "CANCELLED", "EXPIRED"],
            ["CONFIRMED", "CANCELLED", "EXPIRED"],
            "CASE WHEN status::text = 'CONFIRMED' THEN 'ALLOCATED' "
            "ELSE status::text END",
            "CASE WHEN status::text = 'ALLOCATED' THEN 'CONFIRMED' "
            "WHEN status::text IN ('WAITING', 'CONVERTED') THEN 'EXPIRED' "
            "ELSE status::text END",
        ),
        (
            "reservations",
            "status",
            ["ACTIVE", "CANCELLED", "RETURNED"],
            ["CONFIRMED", "CANCELLED"],
            "CASE WHEN status::text = 'CONFIRMED' THEN 'ACTIVE' ELSE status::text END",
            "CASE WHEN status::text = 'ACTIVE' THEN 'CONFIRMED' "
            "WHEN status::text = 'RETURNED' THEN 'CANCELLED' ELSE status::text END",
        ),
    ]
    for table, enum_name, new_values, old_values, up_cast, down_cast in definitions:
        index = f"uq_{table}__catalog_item_id_patron_id_status"
        op.drop_index(index, table_name=table)
        if postgres:
            values = new_values if upgrade else old_values
            temporary = enum_name + "_replacement"
            sa.Enum(*values, name=temporary).create(op.get_bind())
            cast = up_cast if upgrade else down_cast
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN status TYPE {temporary} "
                f"USING ({cast})::{temporary}"
            )
            current_name = (
                "reservationstatus"
                if table == "reservations" and not upgrade
                else enum_name
            )
            target_name = (
                "reservationstatus"
                if table == "reservations" and upgrade
                else enum_name
            )
            sa.Enum(name=current_name).drop(op.get_bind())
            op.execute(f"ALTER TYPE {temporary} RENAME TO {target_name}")
        elif upgrade:
            source, target = (
                "CONFIRMED",
                "ALLOCATED" if table == "item_holds" else "ACTIVE",
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET status = :target WHERE status = :source"
                ).bindparams(target=target, source=source)
            )
        else:
            target = "ALLOCATED" if table == "item_holds" else "ACTIVE"
            op.execute(
                sa.text(
                    f"UPDATE {table} SET status = 'CONFIRMED' WHERE status = :target"
                ).bindparams(target=target)
            )
            states = "'WAITING', 'CONVERTED'" if table == "item_holds" else "'RETURNED'"
            terminal = "EXPIRED" if table == "item_holds" else "CANCELLED"
            op.execute(
                f"UPDATE {table} SET status = '{terminal}' WHERE status IN ({states})"
            )
        active = (
            ("ALLOCATED" if table == "item_holds" else "ACTIVE")
            if upgrade
            else "CONFIRMED"
        )
        op.create_index(
            index,
            table,
            ["catalog_item_id", "patron_id", "status"],
            unique=True,
            postgresql_where=sa.text(f"status = '{active}'"),
            sqlite_where=sa.text(f"status = '{active}'"),
        )


def upgrade() -> None:
    _statuses(True)
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_reservations__hold_id", "item_holds", ["hold_id"], ["id"]
        )
        batch.create_unique_constraint("uq_reservations__hold_id", ["hold_id"])


def downgrade() -> None:
    with op.batch_alter_table("reservations") as batch:
        batch.drop_constraint("uq_reservations__hold_id", type_="unique")
        batch.drop_constraint("fk_reservations__hold_id", type_="foreignkey")
        batch.drop_column("hold_id")
    _statuses(False)
