from pydantic import Field

from backend.domains.base import DomainModel


class User(DomainModel):
    id: int
    name: str = Field(min_length=1, max_length=200)
