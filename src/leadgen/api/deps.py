"""API dependencies for dependency injection."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from leadgen.config import settings
from leadgen.models.database import async_session_maker

# API Key security scheme
api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify API key and return user info.

    For now, this is a placeholder. In production, this should:
    1. Hash the API key
    2. Look it up in the database
    3. Return the associated user/permissions
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # TODO: Implement proper API key verification against database
    # For now, check against hardcoded key
    if api_key == settings.hardcoded_api_key:
        return {
            "user_id": "default-user",
            "api_key_id": "hardcoded-key",
            "scopes": ["read", "write"],
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


# Type aliases for cleaner dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[dict, Depends(verify_api_key)]
