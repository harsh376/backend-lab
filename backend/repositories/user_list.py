"""User list repository contract with PostgreSQL and SQLite implementations."""

from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from backend.db.models import Content as ContentRow
from backend.db.models import User as UserRow
from backend.db.models import UserList as UserListRow
from backend.db.models import UserListContent as UserListContentRow
from backend.domains.user_list import UserList, UserListContent
from backend.repositories import RepositoryError, RepositoryUnavailableError, SortOrder


class UserNotFoundError(RepositoryError):
    pass


class UserListNotFoundError(RepositoryError):
    pass


class UserListAlreadyExistsError(RepositoryError):
    pass


class ContentNotFoundError(RepositoryError):
    pass


class ContentAlreadyInListError(RepositoryError):
    pass


class ContentNotInListError(RepositoryError):
    pass


class UserListRepository(Protocol):
    async def create_user_list(self, user_id: int, list_name: str) -> UserList: ...

    async def retrieve_user_lists(
        self,
        user_id: int,
        *,
        cursor: int | None = None,
        page_size: int = 20,
        sort: SortOrder = "desc",
    ) -> list[UserList]: ...

    async def get_user_list(self, user_id: int, user_list_id: int) -> UserList: ...

    async def add_content(
        self, user_id: int, user_list_id: int, content_id: int
    ) -> UserListContent: ...

    async def remove_content(
        self, user_id: int, user_list_id: int, user_list_content_id: int
    ) -> None: ...


class PostgresUserListRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_user_list(self, user_id: int, list_name: str) -> UserList:
        try:
            async with self._sessions() as session:
                user_exists = await session.scalar(
                    select(UserRow.id).where(UserRow.id == user_id)
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error

        if user_exists is None:
            raise UserNotFoundError(user_id)

        row = UserListRow(user_id=user_id, name=list_name)
        try:
            async with self._sessions.begin() as session:
                session.add(row)
                await session.flush()
                await session.refresh(row)
        except IntegrityError as error:
            raise UserListAlreadyExistsError(list_name) from error
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error
        return _user_list_to_domain(row)

    async def retrieve_user_lists(
        self,
        user_id: int,
        *,
        cursor: int | None = None,
        page_size: int = 20,
        sort: SortOrder = "desc",
    ) -> list[UserList]:
        order_column = UserListRow.id.desc() if sort == "desc" else UserListRow.id.asc()
        stmt = (
            select(UserListRow)
            .where(UserListRow.user_id == user_id)
            .order_by(order_column)
            .limit(page_size)
        )
        if cursor is not None:
            stmt = stmt.where(
                UserListRow.id < cursor if sort == "desc" else UserListRow.id > cursor
            )

        try:
            async with self._sessions() as session:
                rows = await session.scalars(stmt)
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error
        return [_user_list_to_domain(row) for row in rows]

    async def get_user_list(self, user_id: int, user_list_id: int) -> UserList:
        row = await self._get_owned_row(user_id, user_list_id)
        return _user_list_to_domain(row)

    async def add_content(
        self, user_id: int, user_list_id: int, content_id: int
    ) -> UserListContent:
        await self._get_owned_row(user_id, user_list_id)

        try:
            async with self._sessions() as session:
                content_exists = await session.scalar(
                    select(ContentRow.id).where(ContentRow.id == content_id)
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error

        if content_exists is None:
            raise ContentNotFoundError(content_id)

        row = UserListContentRow(user_list_id=user_list_id, content_id=content_id)
        try:
            async with self._sessions.begin() as session:
                session.add(row)
                await session.flush()
                await session.refresh(row)
        except IntegrityError as error:
            raise ContentAlreadyInListError(content_id) from error
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error
        return _user_list_content_to_domain(row)

    async def remove_content(
        self, user_id: int, user_list_id: int, user_list_content_id: int
    ) -> None:
        await self._get_owned_row(user_id, user_list_id)
        try:
            async with self._sessions.begin() as session:
                result = await session.execute(
                    delete(UserListContentRow).where(
                        UserListContentRow.id == user_list_content_id,
                        UserListContentRow.user_list_id == user_list_id,
                    )
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error

        if result.rowcount == 0:
            raise ContentNotInListError(user_list_content_id)

    async def _get_owned_row(self, user_id: int, user_list_id: int) -> UserListRow:
        try:
            async with self._sessions() as session:
                row = await session.scalar(
                    select(UserListRow).where(
                        UserListRow.id == user_list_id,
                        UserListRow.user_id == user_id,
                    )
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailableError(
                "user list repository operation failed"
            ) from error

        if row is None:
            raise UserListNotFoundError(user_list_id)
        return row


def _user_list_to_domain(row: UserListRow) -> UserList:
    return UserList(id=row.id, user_id=row.user_id, name=row.name)


def _user_list_content_to_domain(row: UserListContentRow) -> UserListContent:
    return UserListContent(
        id=row.id, user_list_id=row.user_list_id, content_id=row.content_id
    )
