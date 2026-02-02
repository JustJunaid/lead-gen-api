"""Scraping endpoints for LinkedIn profiles and groups."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, status
from pydantic import BaseModel, Field

from leadgen.api.deps import get_db, DbSession
from leadgen.config import settings
from leadgen.repositories.job_repo import JobRepository
from leadgen.models.job import JobType, JobStatus

router = APIRouter()


# ============================================
# Request/Response Schemas
# ============================================

class GroupScrapeRequest(BaseModel):
    """Request to scrape LinkedIn group members."""

    group_url: str = Field(
        ...,
        description="LinkedIn group URL (e.g., https://www.linkedin.com/groups/8632775/)",
        json_schema_extra={"example": "https://www.linkedin.com/groups/8632775/"},
    )
    member_urls: list[str] | None = Field(
        None,
        description="Pre-extracted member URLs (from PhantomBuster/Sales Nav export)",
    )
    enrich_profiles: bool = Field(
        True,
        description="Whether to enrich profiles with full data",
    )
    find_emails: bool = Field(
        True,
        description="Whether to find and verify emails",
    )
    webhook_url: str | None = Field(
        None,
        description="Webhook URL to notify when complete",
    )


class GroupScrapeResponse(BaseModel):
    """Response for group scrape job."""

    job_id: UUID
    status: str
    message: str
    total_members: int
    estimated_cost: float
    estimated_time_minutes: int


class ProfileScrapeRequest(BaseModel):
    """Request to scrape single LinkedIn profile."""

    linkedin_url: str = Field(
        ...,
        description="LinkedIn profile URL",
        json_schema_extra={"example": "https://www.linkedin.com/in/johndoe/"},
    )
    find_email: bool = Field(
        True,
        description="Whether to find and verify email",
    )


class ProfileScrapeResponse(BaseModel):
    """Response for single profile scrape."""

    linkedin_url: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    location: str | None = None
    email: str | None = None
    email_verified: bool = False


class BulkScrapeRequest(BaseModel):
    """Request to scrape multiple LinkedIn profiles."""

    linkedin_urls: list[str] = Field(
        ...,
        description="List of LinkedIn profile URLs (max 10,000)",
        max_length=10000,
    )
    enrich_profiles: bool = True
    find_emails: bool = True
    webhook_url: str | None = None


class BulkScrapeResponse(BaseModel):
    """Response for bulk scrape job."""

    job_id: UUID
    status: str
    total_profiles: int
    estimated_cost: float
    estimated_time_minutes: int


class ExtensionProfile(BaseModel):
    """Profile data from Chrome extension."""

    name: str = Field(..., description="Full name from LinkedIn profile")
    headline: str | None = Field(None, description="Job title/headline")
    company: str | None = Field(None, description="Current company name")
    linkedin: str = Field(..., description="LinkedIn profile URL")
    about: str | None = Field(None, description="About/bio section")
    location: str | None = Field(None, description="Location")
    connections: str | None = Field(None, description="Connection count")
    followers: str | None = Field(None, description="Follower count")


class ExtensionImportRequest(BaseModel):
    """Request to import profiles from Chrome extension."""

    profiles: list[ExtensionProfile] = Field(
        ...,
        description="List of profiles scraped by extension",
        max_length=10000,
    )
    enrich_profiles: bool = Field(
        True,
        description="Fetch full profile data via RapidAPI",
    )
    find_emails: bool = Field(
        True,
        description="Find and verify emails",
    )
    webhook_url: str | None = Field(
        None,
        description="Webhook URL to notify when complete",
    )


class ExtensionImportResponse(BaseModel):
    """Response for extension import job."""

    job_id: UUID
    status: str
    message: str
    total_profiles: int
    estimated_cost: float
    estimated_time_minutes: int


# ============================================
# Endpoints
# ============================================

@router.post("/group", response_model=GroupScrapeResponse)
async def scrape_linkedin_group(
    request: GroupScrapeRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
) -> GroupScrapeResponse:
    """
    Scrape LinkedIn group members and enrich with emails.

    ## Workflow

    1. **Provide member URLs**: Export group members using PhantomBuster or Sales Nav,
       then upload the URLs here for enrichment.

    2. **Profile enrichment**: We'll fetch full profile data for each member
       using cookie-less API (safe, no account risk).

    3. **Email finding**: For each profile with a company domain, we'll generate
       email permutations and verify them.

    ## Limitations

    - LinkedIn only shows 2,500 most recent group members
    - Use Sales Navigator filters to get more members
    - You must be a member of private groups to export members

    ## Cost Estimate

    - Profile enrichment: $0.002 per profile
    - Email verification: Uses your API (free)
    - 8,000 members ≈ $16 total

    ## Example with PhantomBuster Export

    1. Use PhantomBuster "LinkedIn Group Members Export" to get member URLs
    2. Download the CSV and extract the LinkedIn URLs
    3. POST those URLs to this endpoint

    """
    # Validate we have member URLs
    if not request.member_urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="member_urls is required. Export group members using PhantomBuster or Sales Nav first.",
        )

    total_members = len(request.member_urls)

    # Calculate estimates
    cost_per_profile = 0.002  # RapidAPI rate
    estimated_cost = total_members * cost_per_profile
    estimated_time = (total_members / 50) * 2  # 50 profiles per batch, ~2 min per batch

    # Create async job
    job_repo = JobRepository(db)

    # For now, use a placeholder user_id (will be replaced with auth)
    # In production, get from authenticated user
    from uuid import uuid4
    placeholder_user_id = uuid4()

    job = await job_repo.create(
        user_id=placeholder_user_id,
        job_type=JobType.SCRAPE_PROFILES,
        config={
            "group_url": request.group_url,
            "member_urls": request.member_urls,
            "enrich_profiles": request.enrich_profiles,
            "find_emails": request.find_emails,
            "webhook_url": request.webhook_url,
        },
        total_items=total_members,
        webhook_url=request.webhook_url,
    )

    # Queue Celery task
    from leadgen.workers.tasks.scraping import scrape_batch_profiles
    scrape_batch_profiles.delay(str(job.id))

    return GroupScrapeResponse(
        job_id=job.id,
        status="queued",
        message=f"Job created. Processing {total_members} members.",
        total_members=total_members,
        estimated_cost=round(estimated_cost, 2),
        estimated_time_minutes=int(estimated_time),
    )


@router.post("/group/upload", response_model=GroupScrapeResponse)
async def scrape_group_from_csv(
    file: UploadFile = File(..., description="CSV file with LinkedIn URLs"),
    enrich_profiles: bool = True,
    find_emails: bool = True,
    webhook_url: str | None = None,
    db: DbSession = None,
) -> GroupScrapeResponse:
    """
    Upload a CSV of LinkedIn URLs exported from PhantomBuster or Sales Nav.

    The CSV should have a column with LinkedIn profile URLs.
    Common column names: 'profileUrl', 'linkedin_url', 'LinkedIn URL', 'url'

    ## How to get the CSV

    ### Option 1: PhantomBuster
    1. Run "LinkedIn Group Members Export" phantom
    2. Download results as CSV
    3. Upload here

    ### Option 2: Sales Navigator
    1. Search with "Groups" filter
    2. Use PhantomBuster "Sales Navigator Search Export"
    3. Download and upload here

    ### Option 3: Manual List
    Create a CSV with a 'linkedin_url' column
    """
    import csv
    import io

    # Read CSV
    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    # Find the LinkedIn URL column
    url_columns = ["profileUrl", "linkedin_url", "LinkedIn URL", "url", "Profile URL", "linkedInUrl"]
    url_column = None

    if reader.fieldnames:
        for col in url_columns:
            if col in reader.fieldnames:
                url_column = col
                break

    if not url_column:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not find LinkedIn URL column. Expected one of: {url_columns}. Found: {reader.fieldnames}",
        )

    # Extract URLs
    member_urls = []
    for row in reader:
        url = row.get(url_column, "").strip()
        if url and "linkedin.com" in url:
            member_urls.append(url)

    if not member_urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid LinkedIn URLs found in CSV",
        )

    # Create request and process
    request = GroupScrapeRequest(
        group_url="csv_upload",
        member_urls=member_urls,
        enrich_profiles=enrich_profiles,
        find_emails=find_emails,
        webhook_url=webhook_url,
    )

    # Reuse the main endpoint logic
    total_members = len(member_urls)
    cost_per_profile = 0.002
    estimated_cost = total_members * cost_per_profile
    estimated_time = (total_members / 50) * 2

    job_repo = JobRepository(db)
    from uuid import uuid4
    placeholder_user_id = uuid4()

    job = await job_repo.create(
        user_id=placeholder_user_id,
        job_type=JobType.SCRAPE_PROFILES,
        config={
            "source": "csv_upload",
            "filename": file.filename,
            "member_urls": member_urls,
            "enrich_profiles": enrich_profiles,
            "find_emails": find_emails,
            "webhook_url": webhook_url,
        },
        total_items=total_members,
        webhook_url=webhook_url,
    )

    # Queue Celery task
    from leadgen.workers.tasks.scraping import scrape_batch_profiles
    scrape_batch_profiles.delay(str(job.id))

    return GroupScrapeResponse(
        job_id=job.id,
        status="queued",
        message=f"CSV processed. Found {total_members} LinkedIn URLs. Processing...",
        total_members=total_members,
        estimated_cost=round(estimated_cost, 2),
        estimated_time_minutes=int(estimated_time),
    )


@router.post("/profile", response_model=ProfileScrapeResponse)
async def scrape_single_profile(
    request: ProfileScrapeRequest,
    db: DbSession,
) -> ProfileScrapeResponse:
    """
    Scrape a single LinkedIn profile and optionally find email.

    This is useful for testing or one-off lookups.
    For bulk processing, use /scraping/bulk or /scraping/group.
    """
    from leadgen.services.scraping.group_scraper import LinkedInGroupScraperService

    if not settings.rapidapi_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RapidAPI key not configured",
        )

    # Create a simple mock verifier for now
    class MockVerifier:
        async def verify(self, email: str):
            from dataclasses import dataclass
            @dataclass
            class Result:
                status: str = "pending"
            return Result()

    service = LinkedInGroupScraperService(
        rapidapi_key=settings.rapidapi_key.get_secret_value(),
        email_verifier=MockVerifier(),
    )

    # Process single profile
    results = []
    async for member in service.process_member_urls(
        urls=[request.linkedin_url],
        enrich_profiles=True,
        find_emails=request.find_email,
    ):
        results.append(member)

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not fetch profile",
        )

    profile = results[0]

    return ProfileScrapeResponse(
        linkedin_url=profile.linkedin_url,
        first_name=profile.first_name,
        last_name=profile.last_name,
        full_name=profile.full_name,
        job_title=profile.job_title,
        company_name=profile.company_name,
        company_domain=profile.company_domain,
        location=profile.location,
        email=profile.email,
        email_verified=profile.email_verified,
    )


@router.post("/bulk", response_model=BulkScrapeResponse)
async def scrape_bulk_profiles(
    request: BulkScrapeRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
) -> BulkScrapeResponse:
    """
    Scrape multiple LinkedIn profiles in bulk.

    This creates an async job that processes profiles in the background.
    Use GET /jobs/{job_id} to check progress.

    ## Rate Limits
    - Up to 10,000 profiles per request
    - Processed at ~50 profiles per minute

    ## Cost
    - $0.002 per profile (RapidAPI)
    - Email verification uses your API
    """
    total_profiles = len(request.linkedin_urls)

    if total_profiles > 10000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10,000 profiles per request",
        )

    # Calculate estimates
    cost_per_profile = 0.002
    estimated_cost = total_profiles * cost_per_profile
    estimated_time = (total_profiles / 50) * 2  # ~2 min per 50 profiles

    job_repo = JobRepository(db)
    from uuid import uuid4
    placeholder_user_id = uuid4()

    job = await job_repo.create(
        user_id=placeholder_user_id,
        job_type=JobType.SCRAPE_PROFILES,
        config={
            "linkedin_urls": request.linkedin_urls,
            "enrich_profiles": request.enrich_profiles,
            "find_emails": request.find_emails,
            "webhook_url": request.webhook_url,
        },
        total_items=total_profiles,
        webhook_url=request.webhook_url,
    )

    # Queue Celery task
    from leadgen.workers.tasks.scraping import scrape_batch_profiles
    scrape_batch_profiles.delay(str(job.id))

    return BulkScrapeResponse(
        job_id=job.id,
        status="queued",
        total_profiles=total_profiles,
        estimated_cost=round(estimated_cost, 2),
        estimated_time_minutes=int(estimated_time),
    )


@router.post("/import", response_model=ExtensionImportResponse)
async def import_from_extension(
    request: ExtensionImportRequest,
    db: DbSession,
) -> ExtensionImportResponse:
    """
    Import profiles from Chrome extension.

    This endpoint receives JSON data directly from the LinkedIn scraper extension.
    The extension extracts basic profile info (name, headline, company, LinkedIn URL),
    and this API enriches them with full profile data and verified emails.

    ## Flow

    1. Extension scrapes LinkedIn search results or group members
    2. Extension POSTs profiles to this endpoint
    3. API creates async job and returns job_id
    4. Background worker enriches each profile via RapidAPI
    5. Worker finds and verifies emails
    6. Results available via GET /jobs/{job_id} and /jobs/{job_id}/export

    ## Example Request

    ```json
    {
        "profiles": [
            {
                "name": "John Smith",
                "headline": "Product Manager at Acme Corp",
                "company": "Acme Corp",
                "linkedin": "https://www.linkedin.com/in/johnsmith",
                "location": "San Francisco, CA"
            }
        ],
        "find_emails": true
    }
    ```

    ## Cost

    - Profile enrichment: $0.002 per profile (RapidAPI)
    - Email verification: ~$0.001 per profile (MailTester.ninja)
    """
    if not request.profiles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No profiles provided",
        )

    total_profiles = len(request.profiles)

    # Extract LinkedIn URLs from extension data
    linkedin_urls = []
    extension_data = []  # Store original extension data for reference

    for profile in request.profiles:
        url = profile.linkedin.strip()
        if url and "linkedin.com" in url:
            linkedin_urls.append(url)
            extension_data.append(profile.model_dump())

    if not linkedin_urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid LinkedIn URLs found in profiles",
        )

    # Calculate estimates
    cost_per_profile = 0.003  # RapidAPI + email verification
    estimated_cost = len(linkedin_urls) * cost_per_profile
    estimated_time = (len(linkedin_urls) / 50) * 2  # ~2 min per 50 profiles

    job_repo = JobRepository(db)
    from uuid import uuid4
    placeholder_user_id = uuid4()

    job = await job_repo.create(
        user_id=placeholder_user_id,
        job_type=JobType.SCRAPE_PROFILES,
        config={
            "source": "chrome_extension",
            "linkedin_urls": linkedin_urls,
            "extension_data": extension_data,  # Original data from extension
            "enrich_profiles": request.enrich_profiles,
            "find_emails": request.find_emails,
            "webhook_url": request.webhook_url,
        },
        total_items=len(linkedin_urls),
        webhook_url=request.webhook_url,
    )

    # Queue Celery task
    from leadgen.workers.tasks.scraping import scrape_batch_profiles
    scrape_batch_profiles.delay(str(job.id))

    return ExtensionImportResponse(
        job_id=job.id,
        status="queued",
        message=f"Imported {len(linkedin_urls)} profiles from extension. Processing...",
        total_profiles=len(linkedin_urls),
        estimated_cost=round(estimated_cost, 2),
        estimated_time_minutes=max(1, int(estimated_time)),
    )
