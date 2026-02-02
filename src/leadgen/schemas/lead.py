"""Lead schemas for request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, EmailStr

from leadgen.models.lead import LeadStatus, DataSource


class EmailSchema(BaseModel):
    """Email schema for nested responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    email_type: str | None = None
    is_primary: bool = False
    verification_status: str = "pending"


class CompanySchema(BaseModel):
    """Company schema for nested responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    domain: str | None = None
    industry: str | None = None
    employee_count_range: str | None = None


class LeadBase(BaseModel):
    """Base lead schema with common fields."""

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    seniority_level: str | None = None
    department: str | None = None
    linkedin_url: str | None = None
    linkedin_username: str | None = None
    personal_city: str | None = None
    personal_state: str | None = None
    personal_country: str | None = None

    @field_validator("linkedin_url", mode="before")
    @classmethod
    def normalize_linkedin_url(cls, v: str | None) -> str | None:
        """Normalize LinkedIn URL."""
        if not v:
            return None
        v = v.strip().rstrip("/")
        # Remove tracking parameters
        if "?" in v:
            v = v.split("?")[0]
        return v


class LeadCreate(LeadBase):
    """Schema for creating a lead."""

    source: DataSource = DataSource.API

    # Optional: create with email
    email: EmailStr | None = None

    # Optional: link to existing company
    company_id: UUID | None = None

    # Or create company inline
    company_name: str | None = None
    company_domain: str | None = None


class LeadUpdate(BaseModel):
    """Schema for updating a lead."""

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    seniority_level: str | None = None
    department: str | None = None
    linkedin_url: str | None = None
    personal_city: str | None = None
    personal_state: str | None = None
    personal_country: str | None = None
    status: LeadStatus | None = None
    company_id: UUID | None = None


class LeadResponse(LeadBase):
    """Schema for lead response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: LeadStatus
    source: DataSource
    data_quality_score: float | None = None
    company: CompanySchema | None = None
    emails: list[EmailSchema] = []
    created_at: datetime
    updated_at: datetime
    last_enriched_at: datetime | None = None
    last_scraped_at: datetime | None = None


class LeadSummary(BaseModel):
    """Lightweight lead summary for lists."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None
    status: LeadStatus
    source: DataSource
    company_name: str | None = None
    primary_email: str | None = None
    created_at: datetime


class LeadListResponse(BaseModel):
    """Paginated list of leads."""

    items: list[LeadSummary]
    total: int
    page: int
    per_page: int
    pages: int


class LeadFilter(BaseModel):
    """Filters for lead queries."""

    status: list[LeadStatus] | None = None
    source: list[DataSource] | None = None
    company_domain: str | None = None
    seniority_level: list[str] | None = None
    has_email: bool | None = None
    email_verified: bool | None = None
    search: str | None = Field(None, description="Search in name, job title, company")
    created_after: datetime | None = None
    created_before: datetime | None = None


class LeadBatchCreate(BaseModel):
    """Schema for batch creating leads."""

    leads: list[LeadCreate]
    deduplicate: bool = True


class LeadBatchResponse(BaseModel):
    """Response for batch lead creation."""

    created: int
    duplicates: int
    errors: list[dict] = []
