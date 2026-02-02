"""User and API Key models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadgen.models.base import Base, JSONBType


class User(Base):
    """User model."""

    __tablename__ = "users"

    # Basic Info
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"


class ApiKey(Base):
    """API Key model for authentication."""

    __tablename__ = "api_keys"

    # Foreign Key
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Key Data
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)  # SHA256 of actual key
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False)  # First 10 chars for identification
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Permissions
    scopes: Mapped[dict] = mapped_column(JSONBType, default=["read", "write"])  # Permissions
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix='{self.key_prefix}...', name='{self.name}')>"

    @property
    def is_expired(self) -> bool:
        """Check if API key is expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


class UserSettings(Base):
    """User settings for storing API keys and preferences."""

    __tablename__ = "user_settings"

    # Foreign Key
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Encrypted API Keys (encrypt at application layer)
    openai_api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    anthropic_api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    google_ai_api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    # Preferences
    default_ai_provider: Mapped[str] = mapped_column(String(50), default="openai")
    default_ai_model: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")

    # Rate Limits (user-level overrides)
    scraping_rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=1000)
    ai_requests_per_day: Mapped[int] = mapped_column(Integer, default=500)

    def __repr__(self) -> str:
        return f"<UserSettings(user_id={self.user_id})>"
