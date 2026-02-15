"""Async Job models for background task tracking."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadgen.models.base import Base, JSONBType


class JobType(str, enum.Enum):
    """Job type enum."""

    SCRAPE_PROFILES = "scrape_profiles"
    ENRICH_EMAILS = "enrich_emails"
    GENERATE_CONTENT = "generate_content"
    IMPORT_CSV = "import_csv"
    EXPORT_LEADS = "export_leads"
    BULK_VERIFY = "bulk_verify"


class JobStatus(str, enum.Enum):
    """Job status enum."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AsyncJob(Base):
    """Async Job model for tracking background tasks."""

    __tablename__ = "async_jobs"

    # Foreign Key
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Job Info
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, values_callable=lambda e: [x.value for x in e]), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda e: [x.value for x in e]),
        default=JobStatus.PENDING,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1-10, higher = more urgent

    # Progress Tracking
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)

    # Configuration
    config: Mapped[dict] = mapped_column(JSONBType, nullable=False)  # Job-specific parameters

    # Results
    result: Mapped[dict | None] = mapped_column(JSONBType)  # Summary of results
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict | None] = mapped_column(JSONBType)

    # Timing
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_completion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Celery Integration
    celery_task_id: Mapped[str | None] = mapped_column(String(255), index=True)

    # Webhook
    webhook_url: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    tasks: Mapped[list["JobTask"]] = relationship("JobTask", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<AsyncJob(id={self.id}, type='{self.job_type}', status='{self.status}')>"

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100


class JobTask(Base):
    """Individual task within a job."""

    __tablename__ = "job_tasks"

    # Foreign Key
    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Task Info
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda e: [x.value for x in e]),
        default=JobStatus.PENDING,
        index=True,
    )

    # Task Data
    input_data: Mapped[dict] = mapped_column(JSONBType, nullable=False)  # e.g., {"linkedin_url": "..."}
    output_data: Mapped[dict | None] = mapped_column(JSONBType)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Retry Tracking
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # Completion
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationship
    job: Mapped["AsyncJob"] = relationship("AsyncJob", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<JobTask(id={self.id}, job_id={self.job_id}, status='{self.status}')>"

    @property
    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.attempts < self.max_attempts and self.status == JobStatus.FAILED
