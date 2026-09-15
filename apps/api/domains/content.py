from pydantic import Field

from apps.api.domains.base import DomainModel


class Content(DomainModel):
    id: int
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=200)
