from pydantic import Field

from apps.api.domains.base import DomainModel


class UserList(DomainModel):
    id: int
    user_id: int
    name: str = Field(min_length=1, max_length=200)


class UserListContent(DomainModel):
    id: int
    user_list_id: int
    content_id: int
