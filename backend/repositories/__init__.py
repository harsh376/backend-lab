"""Repository contracts and shared errors."""

from typing import Literal

SortOrder = Literal["asc", "desc"]


class RepositoryError(Exception):
    pass


class RepositoryUnavailableError(RepositoryError):
    pass
