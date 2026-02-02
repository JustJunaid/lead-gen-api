"""Email model."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadgen.models.base import Base


class EmailType(str, enum.Enum):
    """Email type enum."""

    PERSONAL = "personal"
    BUSINESS = "business"
    GENERIC = "generic"


class EmailVerificationStatus(str, enum.Enum):
    """Email verification status enum."""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    UNKNOWN = "unknown"
    DISPOSABLE = "disposable"


class Email(Base):
    """Email model for storing lead emails."""

    __tablename__ = "emails"

    # Constraints
    __table_args__ = (
        UniqueConstraint("lead_id", "email", name="uq_lead_email"),
    )

    # Foreign Key
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Email Data
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email_type: Mapped[EmailType | None] = mapped_column(Enum(EmailType))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Verification
    verification_status: Mapped[EmailVerificationStatus] = mapped_column(
        Enum(EmailVerificationStatus),
        default=EmailVerificationStatus.PENDING,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_provider: Mapped[str | None] = mapped_column(String(50))  # 'internal', 'zerobounce', etc.

    # Source
    source: Mapped[str | None] = mapped_column(String(50))  # 'permutation', 'apollo', 'scraped'
    pattern_used: Mapped[str | None] = mapped_column(String(50))  # 'first.last', 'flast', etc.
    confidence_score: Mapped[float | None] = mapped_column(Numeric(3, 2))

    # Activity Tracking
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationship
    lead = relationship("Lead", back_populates="emails")

    def __repr__(self) -> str:
        return f"<Email(id={self.id}, email='{self.email}', status='{self.verification_status}')>"

    @property
    def domain(self) -> str:
        """Extract domain from email."""
        return self.email.split("@")[1] if "@" in self.email else ""
