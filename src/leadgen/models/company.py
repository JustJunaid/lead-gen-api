"""Company model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, Numeric, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadgen.models.base import Base

if TYPE_CHECKING:
    from leadgen.models.lead import Lead


class Company(Base):
    """Company model for storing company information."""

    __tablename__ = "companies"

    # Basic Info
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), index=True)
    website: Mapped[str | None] = mapped_column(String(500))

    # Company Details
    industry: Mapped[str | None] = mapped_column(String(255))
    employee_count_range: Mapped[str | None] = mapped_column(String(50))  # '1-10', '11-50', etc.
    revenue_range: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500))

    # Location
    headquarters_city: Mapped[str | None] = mapped_column(String(255))
    headquarters_state: Mapped[str | None] = mapped_column(String(100))
    headquarters_country: Mapped[str | None] = mapped_column(String(100))

    # Email Pattern Detection
    detected_email_pattern: Mapped[str | None] = mapped_column(String(50))  # 'first.last', 'flast', etc.
    email_pattern_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))  # 0.00-1.00

    # Source Tracking
    source: Mapped[str | None] = mapped_column(String(50))  # 'apollo', 'sales_nav', 'scraped'
    source_id: Mapped[str | None] = mapped_column(String(255))  # External ID from source

    # Freshness
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_quality_score: Mapped[float | None] = mapped_column(Numeric(3, 2))

    # Relationships
    leads: Mapped[list["Lead"]] = relationship("Lead", back_populates="company")

    def __repr__(self) -> str:
        return f"<Company(id={self.id}, name='{self.name}', domain='{self.domain}')>"
