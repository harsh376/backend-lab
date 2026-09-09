"""Application service coordinating persistence and observability."""

import logging

from app.db.repository import RepositoryUnavailableError, TitleRepository
from app.domain import Title
from app.observability.metrics import Metrics


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
        except RepositoryUnavailableError:
            self._metrics.record_repository_failure()
            raise

        self._record("get", "success", title.id, request_id)
        return title

    async def create(self, title: Title, request_id: str) -> Title:
        try:
            created = await self._repository.create(title)
        except RepositoryUnavailableError:
            self._metrics.record_repository_failure()
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
