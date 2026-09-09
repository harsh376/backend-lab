"""Database models, sessions, and repositories."""

from app.db.models import Base, TitleRow
from app.db.repository import (
    InMemoryTitleRepository,
    PostgresTitleRepository,
    RepositoryError,
    RepositoryUnavailableError,
    TitleAlreadyExistsError,
    TitleNotFoundError,
    TitleRepository,
)
from app.db.session import Database

__all__ = [
    "Base",
    "Database",
    "InMemoryTitleRepository",
    "PostgresTitleRepository",
    "RepositoryError",
    "RepositoryUnavailableError",
    "TitleAlreadyExistsError",
    "TitleNotFoundError",
    "TitleRepository",
    "TitleRow",
]
