"""Lead model - the core entity."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadgen.models.base import Base

if TYPE_CHECKING:
    from leadgen.models.company import Company
    from leadgen.models.email import Email
    from leadgen.models.linkedin_profile import LinkedInProfile


class LeadStatus(str, enum.Enum):
    """Lead status enum."""

    NEW = "new"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    VERIFIED = "verified"
    INVALID = "invalid"
    ARCHIVED = "archived"


class DataSource(str, enum.Enum):
    """Data source enum."""

    APOLLO = "apollo"
    SALES_NAVIGATOR = "sales_navigator"
    LINKEDIN_SCRAPE = "linkedin_scrape"
    MANUAL = "manual"
    CSV_IMPORT = "csv_import"
    API = "api"


class Lead(Base):
    """Lead model - the core entity for storing contact information."""

    __tablename__ = "leads"

    # Foreign Keys
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        index=True,
    )

    # Basic Info
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(500), index=True)

    # Professional Info
    job_title: Mapped[str | None] = mapped_column(String(500))
    job_title_normalized: Mapped[str | None] = mapped_column(String(255))
    seniority_level: Mapped[str | None] = mapped_column(String(50))  # 'c_level', 'vp', 'director', 'manager', 'staff'
    department: Mapped[str | None] = mapped_column(String(100))

    # LinkedIn
    linkedin_url: Mapped[str | None] = mapped_column(String(500), unique=True, index=True)
    linkedin_username: Mapped[str | None] = mapped_column(String(255))

    # Personal Location
    personal_city: Mapped[str | None] = mapped_column(String(255))
    personal_state: Mapped[str | None] = mapped_column(String(100))
    personal_country: Mapped[str | None] = mapped_column(String(100))

    # Status & Quality
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus),
        default=LeadStatus.NEW,
        index=True,
    )
    data_quality_score: Mapped[float | None] = mapped_column(Numeric(3, 2))

    # Source Tracking
    source: Mapped[DataSource] = mapped_column(Enum(DataSource), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255))  # External ID from source
    source_file: Mapped[str | None] = mapped_column(String(500))  # For CSV imports

    # Deduplication
    dedup_key: Mapped[str | None] = mapped_column(String(255), index=True)
    merged_into_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
    )

    # Timestamps
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    company: Mapped["Company | None"] = relationship("Company", back_populates="leads")
    emails: Mapped[list["Email"]] = relationship("Email", back_populates="lead", cascade="all, delete-orphan")
    linkedin_profiles: Mapped[list["LinkedInProfile"]] = relationship(
        "LinkedInProfile", back_populates="lead", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Lead(id={self.id}, name='{self.full_name}', linkedin='{self.linkedin_url}')>"

    @property
    def primary_email(self) -> "Email | None":
        """Get the primary email for this lead."""
        for email in self.emails:
            if email.is_primary:
                return email
        return self.emails[0] if self.emails else None
