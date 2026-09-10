"""Tests for application service outcome telemetry."""

import logging
from dataclasses import dataclass, field

import pytest

from app.db.repository import (
    InMemoryTitleRepository,
    RepositoryUnavailableError,
    TitleAlreadyExistsError,
    TitleNotFoundError,
)
from app.domain import Title
from app.service import TitleService


@dataclass
class RecordingMetrics:
    operations: list[tuple[str, str]] = field(default_factory=list)
    repository_failures: list[str] = field(default_factory=list)

    def record_title_operation(self, operation: str, outcome: str) -> None:
        self.operations.append((operation, outcome))

    def record_repository_failure(self, operation: str) -> None:
        self.repository_failures.append(operation)


class UnavailableRepository:
    async def get_by_id(self, title_id: str) -> Title:
        raise RepositoryUnavailableError(title_id)

    async def create(self, title: Title) -> Title:
        raise RepositoryUnavailableError(title.id)


def make_service(repository) -> tuple[TitleService, RecordingMetrics]:
    metrics = RecordingMetrics()
    logger = logging.getLogger(f"test-service-{id(metrics)}")
    logger.addHandler(logging.NullHandler())
    return TitleService(repository, metrics, logger), metrics


async def test_get_records_success_and_not_found() -> None:
    service, metrics = make_service(
        InMemoryTitleRepository([Title(id="movie-123", name="Example Movie")])
    )

    await service.get("movie-123", "request-1")
    with pytest.raises(TitleNotFoundError):
        await service.get("missing", "request-2")

    assert metrics.operations == [("get", "success"), ("get", "not_found")]


async def test_create_records_success_and_already_exists() -> None:
    service, metrics = make_service(InMemoryTitleRepository())
    title = Title(id="movie-123", name="Example Movie")

    await service.create(title, "request-1")
    with pytest.raises(TitleAlreadyExistsError):
        await service.create(title, "request-2")

    assert metrics.operations == [
        ("create", "success"),
        ("create", "already_exists"),
    ]


async def test_repository_unavailability_records_operation_and_outcome() -> None:
    service, metrics = make_service(UnavailableRepository())

    with pytest.raises(RepositoryUnavailableError):
        await service.get("movie-123", "request-1")
    with pytest.raises(RepositoryUnavailableError):
        await service.create(
            Title(id="movie-456", name="Another Movie"),
            "request-2",
        )

    assert metrics.operations == [
        ("get", "unavailable"),
        ("create", "unavailable"),
    ]
    assert metrics.repository_failures == ["get", "create"]
