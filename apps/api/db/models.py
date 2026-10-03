"""SQLAlchemy persistence models."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
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


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
