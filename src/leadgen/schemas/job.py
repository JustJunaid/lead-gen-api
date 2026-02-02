"""Job schemas for request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from leadgen.models.job import JobType, JobStatus


class JobResponse(BaseModel):
    """Schema for job response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: JobType
    status: JobStatus
    priority: int
    total_items: int
    processed_items: int
    failed_items: int
    config: dict
    result: dict | None = None
    error_message: str | None = None
    progress_percentage: float
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    estimated_completion: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    """Paginated list of jobs."""

    items: list[JobResponse]
    total: int
    page: int
    per_page: int
    pages: int


class JobCreate(BaseModel):
    """Schema for creating a job."""

    job_type: JobType
    config: dict
    priority: int = 5
    webhook_url: str | None = None
