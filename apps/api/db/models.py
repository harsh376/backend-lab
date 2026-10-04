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


class Status(enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CatalogItemReservation(Base):
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
    status: Mapped[Status] = mapped_column()

    __table_args__ = (
        Index(
            "uq_reservations__catalog_item_id_patron_id_status",
            "catalog_item_id",
            "patron_id",
            "status",
            unique=True,
            postgresql_where=text("status = 'CONFIRMED'"),
            sqlite_where=text("status = 'CONFIRMED'"),
        ),
    )


class HoldStatus(enum.Enum):
    CONFIRMED = "confirmed"
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
        Index(
            "uq_item_holds__catalog_item_id_patron_id_status",
            "catalog_item_id",
            "patron_id",
            "status",
            unique=True,
            postgresql_where=text("status = 'CONFIRMED'"),
            sqlite_where=text("status = 'CONFIRMED'"),
        ),
    )


class WaitlistRecord(Base):
    __tablename__ = "wait_list_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_item_id: Mapped[int] = mapped_column(
        ForeignKey(
            column="catalog_items.id",
            name="fk_wait_list_records__catalog_item_id",
            ondelete="CASCADE",
        )
    )
    patron_id: Mapped[int] = mapped_column(
        ForeignKey(column="patrons.id", name="fk_wait_list_records__patron_id")
    )
    is_active: Mapped[bool] = mapped_column()

    __table_args__ = (
        Index(
            "uq_wait_list_records__catalog_item_id_patron_id_is_active",
            "catalog_item_id",
            "patron_id",
            "is_active",
            unique=True,
            postgresql_where=(is_active.is_(True)),
            sqlite_where=(is_active.is_(True)),
        ),
    )
