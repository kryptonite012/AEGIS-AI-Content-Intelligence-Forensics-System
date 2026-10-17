from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=200)


class UserRef(ORM):
    id: uuid.UUID
    display_name: str
    email: str


class Message(BaseModel):
    message: str
    details: dict[str, Any] | None = None


class Timestamped(ORM):
    created_at: datetime
