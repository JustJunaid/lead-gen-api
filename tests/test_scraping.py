"""Tests for scraping endpoints."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_scrape_single_profile_missing_api_key(client: AsyncClient):
    """Test single profile scrape fails without API key."""
    response = await client.post(
        "/api/v1/scraping/profile",
        json={"linkedin_url": "https://www.linkedin.com/in/johndoe/"},
    )
    assert response.status_code == 503
    assert "RapidAPI key not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_scrape_group_missing_member_urls(client: AsyncClient):
    """Test group scrape requires member_urls."""
    response = await client.post(
        "/api/v1/scraping/group",
        json={
            "group_url": "https://www.linkedin.com/groups/8632775/",
            "member_urls": None,
        },
    )
    assert response.status_code == 400
    assert "member_urls is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_scrape_group_success(client: AsyncClient):
    """Test group scrape creates job successfully."""
    member_urls = [
        "https://www.linkedin.com/in/johndoe/",
        "https://www.linkedin.com/in/janedoe/",
    ]

    response = await client.post(
        "/api/v1/scraping/group",
        json={
            "group_url": "https://www.linkedin.com/groups/8632775/",
            "member_urls": member_urls,
            "enrich_profiles": True,
            "find_emails": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["total_members"] == 2
    assert data["job_id"] is not None
    assert data["estimated_cost"] == 0.0  # 2 * 0.002 rounded


@pytest.mark.asyncio
async def test_scrape_bulk_success(client: AsyncClient):
    """Test bulk scrape creates job successfully."""
    linkedin_urls = [
        "https://www.linkedin.com/in/profile1/",
        "https://www.linkedin.com/in/profile2/",
        "https://www.linkedin.com/in/profile3/",
    ]

    response = await client.post(
        "/api/v1/scraping/bulk",
        json={
            "linkedin_urls": linkedin_urls,
            "enrich_profiles": True,
            "find_emails": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["total_profiles"] == 3
    assert data["job_id"] is not None


@pytest.mark.asyncio
async def test_scrape_bulk_exceeds_limit(client: AsyncClient):
    """Test bulk scrape rejects too many URLs."""
    # Create 10,001 fake URLs
    linkedin_urls = [f"https://www.linkedin.com/in/profile{i}/" for i in range(10001)]

    response = await client.post(
        "/api/v1/scraping/bulk",
        json={
            "linkedin_urls": linkedin_urls,
        },
    )

    # Pydantic max_length validation returns 422 Unprocessable Entity
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_csv_upload_invalid_file(client: AsyncClient):
    """Test CSV upload with missing URL column."""
    csv_content = b"name,email\nJohn,john@example.com"

    response = await client.post(
        "/api/v1/scraping/group/upload",
        files={"file": ("test.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 400
    assert "Could not find LinkedIn URL column" in response.json()["detail"]


@pytest.mark.asyncio
async def test_csv_upload_success(client: AsyncClient):
    """Test CSV upload with valid LinkedIn URLs."""
    csv_content = b"name,linkedin_url\nJohn,https://www.linkedin.com/in/johndoe/\nJane,https://www.linkedin.com/in/janedoe/"

    response = await client.post(
        "/api/v1/scraping/group/upload",
        files={"file": ("test.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["total_members"] == 2
