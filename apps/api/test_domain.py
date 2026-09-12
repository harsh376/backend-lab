import pytest
from pydantic import ValidationError

from apps.api.domain import Title


def test_title_is_validated() -> None:
    with pytest.raises(ValidationError):
        Title(id="movie-123", name="")


def test_title_is_immutable() -> None:
    title = Title(id="movie-123", name="Example Movie")

    with pytest.raises(ValidationError, match="Instance is frozen"):
        title.name = "Changed"
