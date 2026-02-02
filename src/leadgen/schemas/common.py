"""Common schemas used across the API."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str
    success: bool = True


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int

    @property
    def has_next(self) -> bool:
        """Check if there's a next page."""
        return self.page < self.pages

    @property
    def has_prev(self) -> bool:
        """Check if there's a previous page."""
        return self.page > 1
