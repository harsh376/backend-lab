"""Title repository contract and PostgreSQL implementation."""

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.db.models import TitleRow
from apps.api.domains.title import Title
from apps.api.repositories import RepositoryError, RepositoryUnavailableError


class TitleNotFoundError(RepositoryError):
    pass


class TitleAlreadyExistsError(RepositoryError):
    pass


class TitleRepository(Protocol):
    async def get_by_id(self, title_id: str) -> Title: ...

    async def create(self, title: Title) -> Title: ...


class PostgresTitleRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_by_id(self, title_id: str) -> Title:
        try:
            async with self._sessions() as session:
                row = await session.scalar(
                    select(TitleRow).where(TitleRow.id == title_id)
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "title repository operation failed"
            ) from error

        if row is None:
            raise TitleNotFoundError(title_id)
        return _to_domain(row)

    async def create(self, title: Title) -> Title:
        try:
            async with self._sessions.begin() as session:
                session.add(_to_row(title))
        except IntegrityError as error:
            raise TitleAlreadyExistsError(title.id) from error
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "title repository operation failed"
            ) from error
        return title


def _to_domain(row: TitleRow) -> Title:
    return Title(id=row.id, name=row.name, description=row.description)


def _to_row(title: Title) -> TitleRow:
    return TitleRow(id=title.id, name=title.name, description=title.description)
