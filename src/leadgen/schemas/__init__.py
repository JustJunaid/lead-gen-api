"""Pydantic schemas for request/response validation."""

from leadgen.schemas.lead import (
    LeadCreate,
    LeadUpdate,
    LeadResponse,
    LeadListResponse,
    LeadFilter,
)
from leadgen.schemas.job import JobResponse, JobListResponse
from leadgen.schemas.common import PaginatedResponse, MessageResponse

__all__ = [
    "LeadCreate",
    "LeadUpdate",
    "LeadResponse",
    "LeadListResponse",
    "LeadFilter",
    "JobResponse",
    "JobListResponse",
    "PaginatedResponse",
    "MessageResponse",
]
