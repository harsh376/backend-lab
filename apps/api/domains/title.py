from pydantic import Field

from apps.api.domains.base import DomainModel


class Title(DomainModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
