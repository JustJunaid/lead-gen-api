"""Full enrichment pipeline for leads."""

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator

import structlog

from leadgen.services.enrichment.email_verifier import (
    EmailPermutator,
    EmailVerifierProtocol,
    VerificationResult,
    VerificationStatus,
)

logger = structlog.get_logger()


@dataclass
class EnrichmentConfig:
    """Configuration for enrichment pipeline."""

    find_emails: bool = True
    max_email_permutations: int = 13
    stop_on_valid_email: bool = True
    concurrent_verifications: int = 3
    retry_failed_verifications: bool = False


@dataclass
class EnrichedLead:
    """Fully enriched lead data."""

    linkedin_url: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    email: str | None = None
    email_status: VerificationStatus = VerificationStatus.PENDING
    all_emails_tried: list[str] = field(default_factory=list)
    profile_data: dict | None = None
    enrichment_error: str | None = None


class EnrichmentPipeline:
    """
    Full enrichment pipeline for leads.

    Flow:
    1. Receive profile data (from scraper or existing)
    2. Extract company domain
    3. Generate email permutations
    4. Verify emails until valid one found
    5. Update company pattern database
    """

    def __init__(
        self,
        email_verifier: EmailVerifierProtocol,
        config: EnrichmentConfig | None = None,
        company_patterns: dict[str, str] | None = None,
    ):
        self.email_verifier = email_verifier
        self.config = config or EnrichmentConfig()
        self.permutator = EmailPermutator(known_patterns=company_patterns or {})
        self._pattern_cache: dict[str, str] = company_patterns or {}

    async def enrich_lead(
        self,
        linkedin_url: str,
        first_name: str | None = None,
        last_name: str | None = None,
        company_domain: str | None = None,
        profile_data: dict | None = None,
    ) -> EnrichedLead:
        """
        Enrich a single lead with email.

        Args:
            linkedin_url: LinkedIn profile URL
            first_name: First name (or extract from profile_data)
            last_name: Last name (or extract from profile_data)
            company_domain: Company domain for email generation
            profile_data: Raw profile data from scraper

        Returns:
            Enriched lead with email (if found)
        """
        lead = EnrichedLead(linkedin_url=linkedin_url)

        # Extract data from profile if provided
        if profile_data:
            lead.first_name = profile_data.get("firstName") or first_name
            lead.last_name = profile_data.get("lastName") or last_name
            lead.full_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip()
            lead.job_title = profile_data.get("headline") or profile_data.get("title")
            lead.headline = profile_data.get("headline")
            lead.summary = profile_data.get("summary")
            lead.location = profile_data.get("location")

            # Extract company info
            experiences = profile_data.get("experiences") or profile_data.get("positions", [])
            if experiences:
                current = experiences[0]  # Most recent
                lead.company_name = current.get("companyName") or current.get("company")
                lead.company_domain = company_domain or self._extract_domain(current)

            lead.profile_data = profile_data
        else:
            lead.first_name = first_name
            lead.last_name = last_name
            lead.full_name = f"{first_name or ''} {last_name or ''}".strip()
            lead.company_domain = company_domain

        # Find email if configured
        if self.config.find_emails and lead.first_name and lead.last_name and lead.company_domain:
            await self._find_email(lead)

        return lead

    async def enrich_leads(
        self,
        leads: list[dict],
        batch_size: int = 10,
    ) -> AsyncIterator[EnrichedLead]:
        """
        Enrich multiple leads with streaming results.

        Args:
            leads: List of lead dicts with linkedin_url, first_name, last_name, company_domain
            batch_size: Number of leads to process concurrently

        Yields:
            Enriched leads as they complete
        """
        for i in range(0, len(leads), batch_size):
            batch = leads[i : i + batch_size]
            tasks = [
                self.enrich_lead(
                    linkedin_url=lead["linkedin_url"],
                    first_name=lead.get("first_name"),
                    last_name=lead.get("last_name"),
                    company_domain=lead.get("company_domain"),
                    profile_data=lead.get("profile_data"),
                )
                for lead in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for lead_data, result in zip(batch, results):
                if isinstance(result, Exception):
                    yield EnrichedLead(
                        linkedin_url=lead_data["linkedin_url"],
                        enrichment_error=str(result),
                    )
                else:
                    yield result

    async def _find_email(self, lead: EnrichedLead) -> None:
        """Find and verify email for a lead."""
        if not lead.first_name or not lead.last_name or not lead.company_domain:
            return

        # Generate permutations
        permutations = self.permutator.generate(
            first_name=lead.first_name,
            last_name=lead.last_name,
            domain=lead.company_domain,
            max_permutations=self.config.max_email_permutations,
        )

        if not permutations:
            logger.warning(
                "No email permutations generated",
                first_name=lead.first_name,
                last_name=lead.last_name,
                domain=lead.company_domain,
            )
            return

        lead.all_emails_tried = permutations

        # Verify emails
        for email in permutations:
            try:
                result = await self.email_verifier.verify(email)

                if result.status == VerificationStatus.VALID:
                    lead.email = email
                    lead.email_status = VerificationStatus.VALID

                    # Learn the pattern for this domain
                    pattern = self.permutator.detect_pattern(
                        email, lead.first_name, lead.last_name
                    )
                    if pattern:
                        self._pattern_cache[lead.company_domain] = pattern
                        self.permutator.known_patterns[lead.company_domain] = pattern
                        logger.info(
                            "Learned email pattern",
                            domain=lead.company_domain,
                            pattern=pattern,
                        )

                    if self.config.stop_on_valid_email:
                        return

                elif result.status == VerificationStatus.CATCH_ALL:
                    # Keep catch-all as fallback if no valid found
                    if not lead.email:
                        lead.email = email
                        lead.email_status = VerificationStatus.CATCH_ALL

            except Exception as e:
                logger.warning("Email verification failed", email=email, error=str(e))
                continue

        if not lead.email:
            lead.email_status = VerificationStatus.INVALID
            logger.debug(
                "No valid email found",
                first_name=lead.first_name,
                last_name=lead.last_name,
                domain=lead.company_domain,
                tried=len(permutations),
            )

    def _extract_domain(self, experience: dict) -> str | None:
        """Extract domain from company info in experience."""
        # Try company LinkedIn URL first
        company_url = experience.get("companyLinkedInUrl") or experience.get("companyUrl")
        if company_url and "linkedin.com/company/" in company_url:
            # Would need to look up company to get domain
            pass

        # Try company website
        website = experience.get("companyWebsite") or experience.get("website")
        if website:
            from urllib.parse import urlparse

            try:
                parsed = urlparse(website if website.startswith("http") else f"https://{website}")
                domain = parsed.netloc or parsed.path
                # Remove www prefix
                if domain.startswith("www."):
                    domain = domain[4:]
                return domain
            except Exception:
                pass

        return None

    def get_learned_patterns(self) -> dict[str, str]:
        """Get all learned email patterns."""
        return self._pattern_cache.copy()
