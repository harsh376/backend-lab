"""SQLAlchemy persistence models."""

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
