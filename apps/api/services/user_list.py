import logging

from apps.api.domains.user_list import UserList, UserListContent
from apps.api.repositories import RepositoryUnavailableError, SortOrder
from apps.api.repositories.user_list import (
    ContentAlreadyInListError,
    ContentNotFoundError,
    ContentNotInListError,
    UserListAlreadyExistsError,
    UserListNotFoundError,
    UserListRepository,
    UserNotFoundError,
)


class UserListService:
    def __init__(
        self,
        repository: UserListRepository,
        logger: logging.Logger,
    ) -> None:
        self._repository = repository
        self._logger = logger

    async def create_user_list(
        self, user_id: int, list_name: str, request_id: str
    ) -> UserList:
        try:
            user_list = await self._repository.create_user_list(user_id, list_name)
        except UserNotFoundError:
            self._record("create_user_list", "user_not_found", user_id, request_id)
            raise
        except UserListAlreadyExistsError:
            self._record("create_user_list", "already_exists", user_id, request_id)
            raise
        except RepositoryUnavailableError:
            self._record("create_user_list", "unavailable", user_id, request_id)
            raise

        self._record("create_user_list", "success", user_id, request_id)
        return user_list

    async def retrieve_user_lists(
        self,
        user_id: int,
        request_id: str,
        *,
        cursor: int | None = None,
        page_size: int = 20,
        sort: SortOrder = "desc",
    ) -> list[UserList]:
        try:
            user_lists = await self._repository.retrieve_user_lists(
                user_id, cursor=cursor, page_size=page_size, sort=sort
            )
        except RepositoryUnavailableError:
            self._record("retrieve_user_lists", "unavailable", user_id, request_id)
            raise

        self._record("retrieve_user_lists", "success", user_id, request_id)
        return user_lists

    async def get_user_list(
        self, user_id: int, user_list_id: int, request_id: str
    ) -> UserList:
        try:
            user_list = await self._repository.get_user_list(user_id, user_list_id)
        except UserListNotFoundError:
            self._record("get_user_list", "not_found", user_id, request_id)
            raise
        except RepositoryUnavailableError:
            self._record("get_user_list", "unavailable", user_id, request_id)
            raise

        self._record("get_user_list", "success", user_id, request_id)
        return user_list

    async def add_user_list_content(
        self, user_id: int, user_list_id: int, content_id: int, request_id: str
    ) -> UserListContent:
        try:
            user_list_content = await self._repository.add_content(
                user_id, user_list_id, content_id
            )
        except UserListNotFoundError:
            self._record("add_user_list_content", "list_not_found", user_id, request_id)
            raise
        except ContentNotFoundError:
            self._record(
                "add_user_list_content", "content_not_found", user_id, request_id
            )
            raise
        except ContentAlreadyInListError:
            self._record(
                "add_user_list_content", "already_in_list", user_id, request_id
            )
            raise
        except RepositoryUnavailableError:
            self._record("add_user_list_content", "unavailable", user_id, request_id)
            raise

        self._record("add_user_list_content", "success", user_id, request_id)
        return user_list_content

    async def remove_user_list_content(
        self,
        user_id: int,
        user_list_id: int,
        user_list_content_id: int,
        request_id: str,
    ) -> None:
        try:
            await self._repository.remove_content(
                user_id, user_list_id, user_list_content_id
            )
        except UserListNotFoundError:
            self._record(
                "remove_user_list_content", "list_not_found", user_id, request_id
            )
            raise
        except ContentNotInListError:
            self._record("remove_user_list_content", "not_in_list", user_id, request_id)
            raise
        except RepositoryUnavailableError:
            self._record("remove_user_list_content", "unavailable", user_id, request_id)
            raise

        self._record("remove_user_list_content", "success", user_id, request_id)

    def _record(
        self,
        operation: str,
        outcome: str,
        user_id: int,
        request_id: str,
    ) -> None:
        self._logger.info(
            "user_list_operation_completed",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "operation": operation,
                "outcome": outcome,
            },
        )
