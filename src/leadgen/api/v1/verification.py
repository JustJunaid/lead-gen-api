"""Email verification endpoint — find and verify emails from lead data."""

import logging

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status

from leadgen.api.deps import CurrentUser
from leadgen.config import settings
from leadgen.services.enrichment.email_verifier import (
    EmailPermutator,
    MailTesterNinjaVerifier,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================
# Request/Response Schemas
# ============================================

class LeadInput(BaseModel):
    """Single lead input for email discovery."""

    first_name: str = Field(..., description="Lead's first name", min_length=1)
    last_name: str = Field(..., description="Lead's last name", min_length=1)
    website: str = Field(..., description="Company website/domain (e.g. acme.com)", min_length=1)


class VerifyRequest(BaseModel):
    """Request to find and verify emails for leads."""

    leads: list[LeadInput] = Field(
        ...,
        description="List of leads to find emails for",
        min_length=1,
    )


class VerifiedLead(BaseModel):
    """A lead with a verified email."""

    first_name: str
    last_name: str
    website: str
    email: str


class VerifyResponse(BaseModel):
    """Response with verified leads only."""

    verified_leads: list[VerifiedLead]
    total_input: int
    total_verified: int


# ============================================
# Endpoints
# ============================================

@router.post("/verify", response_model=VerifyResponse)
async def verify_leads(
    request: VerifyRequest,
    _user: CurrentUser,
) -> VerifyResponse:
    """
    Find and verify email addresses for leads.

    For each lead, generates email permutations from first name, last name,
    and website domain, then verifies each against the mail server.
    Stops at the first valid email found per lead.

    Returns only leads where a valid email was found.
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
            # Strip protocol/www from website to get domain
            domain = lead.website.strip().lower()
            domain = domain.removeprefix("https://").removeprefix("http://")
            domain = domain.removeprefix("www.")
            domain = domain.rstrip("/")

            # Generate email permutations
            permutations = permutator.generate(
                first_name=lead.first_name,
                last_name=lead.last_name,
                domain=domain,
            )

            if not permutations:
                logger.info("No permutations generated for %s %s @ %s", lead.first_name, lead.last_name, domain)
                continue

            logger.info("Verifying %d permutations for %s %s @ %s", len(permutations), lead.first_name, lead.last_name, domain)

            # Verify each permutation, stop at first valid
            for email in permutations:
                result = await verifier.verify(email)
                logger.info("  %s -> status=%s, reason=%s", email, result.status, result.reason)

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
