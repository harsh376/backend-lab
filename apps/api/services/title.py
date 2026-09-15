import logging

from apps.api.domains.title import Title
from apps.api.metrics import Metrics
from apps.api.repositories import RepositoryUnavailableError
from apps.api.repositories.title import (
    TitleAlreadyExistsError,
    TitleNotFoundError,
    TitleRepository,
)


class TitleService:
    def __init__(
        self,
        repository: TitleRepository,
        metrics: Metrics,
        logger: logging.Logger,
    ) -> None:
        self._repository = repository
        self._metrics = metrics
        self._logger = logger

    async def get(self, title_id: str, request_id: str) -> Title:
        try:
            title = await self._repository.get_by_id(title_id)
        except TitleNotFoundError:
            self._record("get", "not_found", title_id, request_id)
            raise
        except RepositoryUnavailableError:
            self._metrics.record_repository_failure("get")
            self._record("get", "unavailable", title_id, request_id)
            raise

        self._record("get", "success", title.id, request_id)
        return title

    async def create(self, title: Title, request_id: str) -> Title:
        try:
            created = await self._repository.create(title)
        except TitleAlreadyExistsError:
            self._record("create", "already_exists", title.id, request_id)
            raise
        except RepositoryUnavailableError:
            self._metrics.record_repository_failure("create")
            self._record("create", "unavailable", title.id, request_id)
            raise

        self._record("create", "success", created.id, request_id)
        return created

    def _record(
        self,
        operation: str,
        outcome: str,
        title_id: str,
        request_id: str,
    ) -> None:
        self._metrics.record_title_operation(operation, outcome)
        self._logger.info(
            "title_operation_completed",
            extra={
                "request_id": request_id,
                "title_id": title_id,
                "operation": operation,
                "outcome": outcome,
            },
        )
