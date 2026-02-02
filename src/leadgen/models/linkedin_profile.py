"""LinkedIn Profile model for storing scraped data."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadgen.models.base import Base, JSONBType


class LinkedInProfile(Base):
    """LinkedIn Profile model for storing scraped profile data."""

    __tablename__ = "linkedin_profiles"

    # Foreign Key
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Profile Data
    headline: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    profile_picture_url: Mapped[str | None] = mapped_column(String(500))
    banner_url: Mapped[str | None] = mapped_column(String(500))

    # Engagement Metrics
    connections_count: Mapped[int | None] = mapped_column(Integer)
    followers_count: Mapped[int | None] = mapped_column(Integer)

    # Structured Data (stored as JSONB for flexibility)
    experiences: Mapped[dict | None] = mapped_column(JSONBType)  # Array of experience objects
    education: Mapped[dict | None] = mapped_column(JSONBType)  # Array of education objects
    skills: Mapped[dict | None] = mapped_column(JSONBType)  # Array of skills
    certifications: Mapped[dict | None] = mapped_column(JSONBType)
    languages: Mapped[dict | None] = mapped_column(JSONBType)

    # Activity Data
    recent_posts: Mapped[dict | None] = mapped_column(JSONBType)  # Last N posts with engagement
    recent_comments: Mapped[dict | None] = mapped_column(JSONBType)  # Last N comments

    # Raw Response
    raw_response: Mapped[dict | None] = mapped_column(JSONBType)  # Full API response for debugging
    scraper_provider: Mapped[str | None] = mapped_column(String(50))  # 'rapidapi', 'brightdata', etc.

    # Timestamps
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Relationship
    lead = relationship("Lead", back_populates="linkedin_profiles")

    def __repr__(self) -> str:
        return f"<LinkedInProfile(id={self.id}, lead_id={self.lead_id}, scraped_at='{self.scraped_at}')>"

    @property
    def latest_experience(self) -> dict | None:
        """Get the most recent experience."""
        if self.experiences and isinstance(self.experiences, list) and len(self.experiences) > 0:
            return self.experiences[0]
        return None
