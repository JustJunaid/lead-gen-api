"""Email verification endpoints — find and verify emails from lead data."""

from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, HTTPException, status

from leadgen.api.deps import CurrentUser, DbSession
from leadgen.config import settings
from leadgen.repositories.job_repo import JobRepository
from leadgen.models.job import JobType, JobStatus
from leadgen.services.enrichment.email_verifier import (
    EmailPermutator,
    MailTesterNinjaVerifier,
    VerificationStatus,
)

router = APIRouter()

MAX_SYNC_LEADS = 50
MAX_SYNC_EMAILS = 50


# ============================================
# Request/Response Schemas
# ============================================

# --- Lead verification (find email from name + website) ---

class LeadInput(BaseModel):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    website: str = Field(..., min_length=1)


class VerifyRequest(BaseModel):
    leads: list[LeadInput] = Field(..., min_length=1, max_length=MAX_SYNC_LEADS)


class VerifiedLead(BaseModel):
    first_name: str
    last_name: str
    website: str
    email: str


class VerifyResponse(BaseModel):
    verified_leads: list[VerifiedLead]
    total_input: int
    total_verified: int


class BatchVerifyRequest(BaseModel):
    leads: list[LeadInput] = Field(..., min_length=1)
    webhook_url: str | None = None


class BatchJobResponse(BaseModel):
    job_id: UUID
    status: str
    total_items: int
    message: str


# --- Email-only verification ---

class EmailVerifyRequest(BaseModel):
    emails: list[EmailStr] = Field(..., min_length=1, max_length=MAX_SYNC_EMAILS)


class EmailVerifyResult(BaseModel):
    email: str
    status: str
    is_deliverable: bool
    is_catch_all: bool
    mx_found: bool
    reason: str | None


class EmailVerifyResponse(BaseModel):
    results: list[EmailVerifyResult]
    total_input: int
    total_valid: int


class BatchEmailVerifyRequest(BaseModel):
    emails: list[EmailStr] = Field(..., min_length=1)
    webhook_url: str | None = None


# ============================================
# Endpoints
# ============================================

@router.post("/verify", response_model=VerifyResponse)
async def verify_leads(
    request: VerifyRequest,
    _user: CurrentUser,
) -> VerifyResponse:
    """
    Find and verify email addresses for leads (sync, max 50 leads).

    For each lead, generates email permutations from first name, last name,
    and website domain, then verifies each against the mail server.
    Stops at the first valid email found per lead.

    For larger batches, use `/verify-batch`.
    """
    if not settings.mailtester_ninja_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification service not configured",
        )

    permutator = EmailPermutator()
    verifier = MailTesterNinjaVerifier(
        api_key=settings.mailtester_ninja_api_key.get_secret_value(),
        timeout=settings.email_verification_timeout,
    )

    verified_leads: list[VerifiedLead] = []

    try:
        for lead in request.leads:
            domain = _clean_domain(lead.website)

            permutations = permutator.generate(
                first_name=lead.first_name,
                last_name=lead.last_name,
                domain=domain,
            )

            if not permutations:
                print(f"[VERIFY] No permutations for {lead.first_name} {lead.last_name} @ {domain}", flush=True)
                continue

            print(f"[VERIFY] Trying {len(permutations)} permutations for {lead.first_name} {lead.last_name} @ {domain}", flush=True)

            for email in permutations:
                result = await verifier.verify(email)
                print(f"[VERIFY]   {email} -> {result.status}, reason={result.reason}", flush=True)

                if result.status == VerificationStatus.VALID:
                    verified_leads.append(
                        VerifiedLead(
                            first_name=lead.first_name,
                            last_name=lead.last_name,
                            website=lead.website,
                            email=email,
                        )
                    )
                    break
    finally:
        await verifier.close()

    return VerifyResponse(
        verified_leads=verified_leads,
        total_input=len(request.leads),
        total_verified=len(verified_leads),
    )


@router.post("/verify-batch", response_model=BatchJobResponse)
async def verify_leads_batch(
    request: BatchVerifyRequest,
    _user: CurrentUser,
    db: DbSession,
) -> BatchJobResponse:
    """
    Find and verify emails for a large batch of leads (async).

    Returns a job ID immediately. Poll `GET /api/v1/jobs/{job_id}` for progress.
    Export results with `GET /api/v1/jobs/{job_id}/export?format=json`.

    Includes domain-level optimizations:
    - Learns email patterns per domain (e.g., first.last@) and reuses them
    - Detects catch-all domains and skips redundant permutations
    - Skips domains with no MX records entirely
    """
    if not settings.mailtester_ninja_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification service not configured",
        )

    job_repo = JobRepository(db)
    placeholder_user_id = uuid4()

    leads_data = [lead.model_dump() for lead in request.leads]

    job = await job_repo.create(
        user_id=placeholder_user_id,
        job_type=JobType.BULK_VERIFY,
        config={
            "mode": "leads",
            "leads": leads_data,
            "webhook_url": request.webhook_url,
        },
        total_items=len(request.leads),
        webhook_url=request.webhook_url,
    )
    await db.commit()

    from leadgen.workers.tasks.verification import verify_leads_batch as verify_task
    verify_task.delay(str(job.id))

    return BatchJobResponse(
        job_id=job.id,
        status="queued",
        total_items=len(request.leads),
        message=f"Processing {len(request.leads)} leads in background. Poll GET /api/v1/jobs/{job.id} for progress.",
    )


@router.post("/verify-email", response_model=EmailVerifyResponse)
async def verify_emails(
    request: EmailVerifyRequest,
    _user: CurrentUser,
) -> EmailVerifyResponse:
    """
    Verify email addresses directly (sync, max 50 emails).

    Takes a list of email addresses and checks each one via MailTester.ninja.
    Returns verification status for every email.

    For larger batches, use `/verify-email-batch`.
    """
    if not settings.mailtester_ninja_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification service not configured",
        )

    verifier = MailTesterNinjaVerifier(
        api_key=settings.mailtester_ninja_api_key.get_secret_value(),
        timeout=settings.email_verification_timeout,
    )

    results: list[EmailVerifyResult] = []
    total_valid = 0

    try:
        for email in request.emails:
            result = await verifier.verify(email)
            print(f"[VERIFY-EMAIL] {email} -> {result.status}, reason={result.reason}", flush=True)

            if result.status == VerificationStatus.VALID:
                total_valid += 1

            results.append(
                EmailVerifyResult(
                    email=email,
                    status=result.status.value,
                    is_deliverable=result.is_deliverable,
                    is_catch_all=result.is_catch_all,
                    mx_found=result.mx_found,
                    reason=result.reason,
                )
            )
    finally:
        await verifier.close()

    return EmailVerifyResponse(
        results=results,
        total_input=len(request.emails),
        total_valid=total_valid,
    )


@router.post("/verify-email-batch", response_model=BatchJobResponse)
async def verify_emails_batch(
    request: BatchEmailVerifyRequest,
    _user: CurrentUser,
    db: DbSession,
) -> BatchJobResponse:
    """
    Verify a large batch of email addresses (async).

    Returns a job ID immediately. Poll `GET /api/v1/jobs/{job_id}` for progress.
    Export results with `GET /api/v1/jobs/{job_id}/export?format=json`.
    """
    if not settings.mailtester_ninja_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification service not configured",
        )

    job_repo = JobRepository(db)
    placeholder_user_id = uuid4()

    job = await job_repo.create(
        user_id=placeholder_user_id,
        job_type=JobType.BULK_VERIFY,
        config={
            "mode": "emails",
            "emails": [str(e) for e in request.emails],
            "webhook_url": request.webhook_url,
        },
        total_items=len(request.emails),
        webhook_url=request.webhook_url,
    )
    await db.commit()

    from leadgen.workers.tasks.verification import verify_emails_batch as verify_email_task
    verify_email_task.delay(str(job.id))

    return BatchJobResponse(
        job_id=job.id,
        status="queued",
        total_items=len(request.emails),
        message=f"Verifying {len(request.emails)} emails in background. Poll GET /api/v1/jobs/{job.id} for progress.",
    )


# ============================================
# Helpers
# ============================================

def _clean_domain(website: str) -> str:
    """Extract clean domain from website input."""
    domain = website.strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.removeprefix("www.")
    domain = domain.rstrip("/")
    return domain
