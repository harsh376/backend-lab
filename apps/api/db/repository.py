"""Repository contract with in-memory and PostgreSQL implementations."""

import asyncio
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.db.models import TitleRow
from apps.api.domain import Title


class RepositoryError(Exception):
    pass


class TitleNotFoundError(RepositoryError):
    pass


class TitleAlreadyExistsError(RepositoryError):
    pass


class RepositoryUnavailableError(RepositoryError):
    pass


class TitleRepository(Protocol):
    async def get_by_id(self, title_id: str) -> Title: ...

    async def create(self, title: Title) -> Title: ...


class InMemoryTitleRepository:
    def __init__(self, titles: list[Title] | None = None) -> None:
        self._titles = {title.id: title for title in titles or []}
        self._lock = asyncio.Lock()

    async def get_by_id(self, title_id: str) -> Title:
        title = self._titles.get(title_id)
        if title is None:
            raise TitleNotFoundError(title_id)
        return title

    async def create(self, title: Title) -> Title:
        async with self._lock:
            if title.id in self._titles:
                raise TitleAlreadyExistsError(title.id)
            self._titles[title.id] = title
        return title


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
