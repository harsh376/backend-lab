"""SQLAlchemy persistence models."""

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StudioRow(Base):
    __tablename__ = "studios"
    __table_args__ = (UniqueConstraint("name", name="uq_studios_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class TitleRow(Base):
    __tablename__ = "titles"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    studio_id: Mapped[int | None] = mapped_column(
        ForeignKey("studios.id", name="fk_titles_studio_id_studios"),
        nullable=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Content(Base):
    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)

    # UQ constraint
    __table_args__ = (UniqueConstraint("title", name="uq_contents_title"),)


class UserList(Base):
    __tablename__ = "user_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_user_lists_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_lists_user_id_name"),
    )


class UserListContent(Base):
    __tablename__ = "user_list_contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_list_id: Mapped[int] = mapped_column(
        ForeignKey(
            "user_lists.id",
            name="fk_user_list_contents_user_list_id_user_lists",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey(
            "contents.id",
            name="fk_user_list_contents_content_id_contents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    __table_args__ = (
        UniqueConstraint(
            "user_list_id",
            "content_id",
            name="uq_user_list_contents_user_list_id_content_id",
        ),
    )


class CatalogItemType(enum.Enum):
    DEVICE = "device"
    BOOK = "book"
    MOVIE = "movie"


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    category: Mapped[str] = mapped_column()
    item_type: Mapped[CatalogItemType] = mapped_column()
    quantity: Mapped[int] = mapped_column()

    __table_args__ = (
        UniqueConstraint(
            "name",
            "category",
            "item_type",
            name="uq_catalog_items__name_category_item_type",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_catalog_items_quantity_nonnegative",
        ),
    )


class Patron(Base):
    __tablename__ = "patrons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()


class ReservationStatus(enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class Reservation(Base):
    hold_id: Mapped[int | None] = mapped_column(
        ForeignKey("item_holds.id", name="fk_reservations__hold_id"),
        unique=True,
        nullable=True,
    )

    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_item_id: Mapped[int] = mapped_column(
        ForeignKey(
            column="catalog_items.id",
            name="fk_reservations__catalog_item_id",
            ondelete="CASCADE",
        )
    )
    patron_id: Mapped[int] = mapped_column(
        ForeignKey(column="patrons.id", name="fk_reservations__patron_id")
    )
    status: Mapped[ReservationStatus] = mapped_column()

    __table_args__ = (
        Index(
            "uq_reservations__catalog_item_id_patron_id_status",
            "catalog_item_id",
            "patron_id",
            "status",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )


class HoldStatus(enum.Enum):
    WAITING = "waiting"
    ALLOCATED = "allocated"
    CONVERTED = "converted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Hold(Base):
    __tablename__ = "item_holds"

    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_item_id: Mapped[int] = mapped_column(
        ForeignKey(
            column="catalog_items.id",
            name="fk_item_holds__catalog_item_id",
            ondelete="CASCADE",
        )
    )
    patron_id: Mapped[int] = mapped_column(
        ForeignKey(column="patrons.id", name="fk_item_holds__patron_id")
    )
    status: Mapped[HoldStatus] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_item_holds_status_expires_at_id", "status", "expires_at", "id"),
        Index(
            "uq_item_holds__catalog_item_id_patron_id_status",
            "catalog_item_id",
            "patron_id",
            "status",
            unique=True,
            postgresql_where=text("status = 'ALLOCATED'"),
            sqlite_where=text("status = 'ALLOCATED'"),
        ),
    )


class NotificationKind(enum.Enum):
    HOLD_EXPIRING = "hold_expiring"
    HOLD_CONVERTED = "hold_converted"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("hold_id", "kind", name="uq_notifications_hold_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patron_id: Mapped[int] = mapped_column(ForeignKey("patrons.id"))
    hold_id: Mapped[int] = mapped_column(
        ForeignKey("item_holds.id", ondelete="CASCADE")
    )
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservations.id"))
    kind: Mapped[NotificationKind] = mapped_column()
    message: Mapped[str] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
