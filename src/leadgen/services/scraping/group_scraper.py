"""LinkedIn Group Member Scraping Service.

This module handles the extraction of LinkedIn group members and orchestrates
the full pipeline: extract URLs → enrich profiles → find emails.

Workflow:
1. Extract group member URLs (requires group membership + PhantomBuster/Sales Nav)
2. Enrich profiles with RapidAPI (cookie-less, safe)
3. Find emails via permutation + verification
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


class GroupScrapingMethod(str, Enum):
    """Methods for extracting group members."""

    PHANTOMBUSTER = "phantombuster"  # Direct group export (2,500 limit)
    SALES_NAV_FILTER = "sales_nav_filter"  # Sales Nav with filters (unlimited)
    CSV_UPLOAD = "csv_upload"  # Manual upload of member URLs


@dataclass
class GroupMember:
    """Extracted group member data."""

    linkedin_url: str
    name: str | None = None
    headline: str | None = None
    profile_id: str | None = None


@dataclass
class EnrichedMember:
    """Fully enriched group member."""

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


class LinkedInGroupScraperService:
    """
    Service for scraping LinkedIn group members.

    This handles the full pipeline:
    1. Extract member URLs from group
    2. Enrich each profile with full data
    3. Find and verify emails

    Usage:
        service = LinkedInGroupScraperService(
            rapidapi_key="...",
            email_verifier=your_verifier,
        )

        # Option 1: Process uploaded CSV of member URLs
        async for member in service.process_member_urls(urls):
            print(f"Enriched: {member.full_name} - {member.email}")

        # Option 2: Full pipeline with PhantomBuster webhook
        job = await service.start_group_scrape(
            group_url="https://www.linkedin.com/groups/8632775/",
            method=GroupScrapingMethod.CSV_UPLOAD,
            member_urls=urls,
        )
    """

    # LinkedIn's hard limit for group member visibility
    LINKEDIN_GROUP_MEMBER_LIMIT = 2500

    # Recommended batch sizes for rate limiting
    PROFILE_ENRICHMENT_BATCH_SIZE = 50
    EMAIL_VERIFICATION_BATCH_SIZE = 10

    def __init__(
        self,
        rapidapi_key: str,
        email_verifier,  # Your email verification service
        rapidapi_host: str = "fresh-linkedin-profile-data.p.rapidapi.com",
        domain_finder=None,  # Optional CompanyDomainFinder instance
    ):
        self.rapidapi_key = rapidapi_key
        self.rapidapi_host = rapidapi_host
        self.email_verifier = email_verifier
        self.domain_finder = domain_finder

    async def process_member_urls(
        self,
        urls: list[str],
        enrich_profiles: bool = True,
        find_emails: bool = True,
        batch_size: int = 50,
    ) -> AsyncIterator[EnrichedMember]:
        """
        Process a list of LinkedIn profile URLs.

        This is the main entry point for processing group members
        when you already have their LinkedIn URLs (from PhantomBuster export,
        Sales Nav export, or manual list).

        Args:
            urls: List of LinkedIn profile URLs
            enrich_profiles: Whether to fetch full profile data
            find_emails: Whether to find and verify emails
            batch_size: How many to process at once

        Yields:
            EnrichedMember objects with full data and emails
        """
        logger.info(
            "Starting group member processing",
            total_urls=len(urls),
            enrich_profiles=enrich_profiles,
            find_emails=find_emails,
        )

        # Process in batches
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]

            logger.info(
                "Processing batch",
                batch_number=i // batch_size + 1,
                batch_size=len(batch),
            )

            # Enrich profiles in parallel
            if enrich_profiles:
                enrichment_tasks = [
                    self._enrich_single_profile(url)
                    for url in batch
                ]
                enriched_profiles = await asyncio.gather(*enrichment_tasks, return_exceptions=True)
            else:
                enriched_profiles = [
                    EnrichedMember(linkedin_url=url)
                    for url in batch
                ]

            # Find emails (sequentially to respect rate limits)
            for profile in enriched_profiles:
                if isinstance(profile, Exception):
                    logger.error("Profile enrichment failed", error=str(profile))
                    continue

                if find_emails and profile.company_domain:
                    profile = await self._find_email_for_profile(profile)

                yield profile

            # Rate limit between batches
            await asyncio.sleep(1)

    async def _enrich_single_profile(self, linkedin_url: str) -> EnrichedMember:
        """
        Enrich a single LinkedIn profile using RapidAPI.

        This is cookie-less and doesn't risk your LinkedIn account.
        """
        import httpx

        # Normalize URL
        linkedin_url = self._normalize_linkedin_url(linkedin_url)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://{self.rapidapi_host}/get-linkedin-profile",
                params={"linkedin_url": linkedin_url},
                headers={
                    "X-RapidAPI-Key": self.rapidapi_key,
                    "X-RapidAPI-Host": self.rapidapi_host,
                },
                timeout=30,
            )

            if response.status_code != 200:
                logger.warning(
                    "Profile enrichment failed",
                    url=linkedin_url,
                    status=response.status_code,
                )
                return EnrichedMember(linkedin_url=linkedin_url)

            data = response.json().get("data", {})

            # Extract company info
            company_name = None
            company_domain = None

            if experiences := data.get("experiences", []):
                if experiences and (company := experiences[0].get("company", {})):
                    company_name = company.get("name")
                    # Try to extract domain from company URL/website
                    company_domain = self._extract_domain(
                        company.get("url") or company.get("website")
                    )

            # Fallback: If no domain found but we have company name, try domain finder
            if not company_domain and company_name and self.domain_finder:
                try:
                    company_domain = await self.domain_finder.find_domain(company_name)
                    if company_domain:
                        logger.info(
                            "Found domain via MX lookup",
                            company=company_name,
                            domain=company_domain,
                        )
                except Exception as e:
                    logger.warning(
                        "Domain finder failed",
                        company=company_name,
                        error=str(e),
                    )

            return EnrichedMember(
                linkedin_url=linkedin_url,
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                full_name=data.get("full_name"),
                job_title=data.get("headline") or data.get("occupation"),
                company_name=company_name,
                company_domain=company_domain,
                location=data.get("location"),
            )

    async def _find_email_for_profile(self, profile: EnrichedMember) -> EnrichedMember:
        """
        Find and verify email for an enriched profile.

        Uses permutation + verification approach:
        1. Generate possible email patterns
        2. Verify each until we find a valid one
        """
        if not profile.company_domain or not profile.first_name:
            return profile

        # Generate email permutations
        permutations = self._generate_email_permutations(
            first_name=profile.first_name,
            last_name=profile.last_name or "",
            domain=profile.company_domain,
        )

        # Verify each permutation
        for email in permutations:
            try:
                result = await self.email_verifier.verify(email)
                if result.status in ("valid", "catch_all"):
                    profile.email = email
                    profile.email_verified = result.status == "valid"
                    break
            except Exception as e:
                logger.warning("Email verification failed", email=email, error=str(e))
                continue

        return profile

    def _generate_email_permutations(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        max_permutations: int = 8,
    ) -> list[str]:
        """Generate possible email patterns sorted by likelihood."""
        first = self._normalize_name(first_name)
        last = self._normalize_name(last_name)

        if not first:
            return []

        patterns = []

        # Most common patterns first
        if last:
            patterns.extend([
                f"{first}.{last}@{domain}",      # john.smith@
                f"{first[0]}{last}@{domain}",   # jsmith@
                f"{first}@{domain}",             # john@
                f"{first}{last}@{domain}",       # johnsmith@
                f"{first}_{last}@{domain}",      # john_smith@
                f"{last}.{first}@{domain}",      # smith.john@
                f"{first[0]}.{last}@{domain}",  # j.smith@
                f"{first}{last[0]}@{domain}",   # johns@
            ])
        else:
            patterns.append(f"{first}@{domain}")

        return patterns[:max_permutations]

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for email generation."""
        import re
        if not name:
            return ""
        # Remove special chars, lowercase
        return re.sub(r"[^a-zA-Z]", "", name).lower()

    def _normalize_linkedin_url(self, url: str) -> str:
        """Normalize LinkedIn URL format."""
        url = url.strip().rstrip("/")
        if "?" in url:
            url = url.split("?")[0]
        return url

    def _extract_domain(self, url: str | None) -> str | None:
        """Extract domain from a URL."""
        if not url:
            return None
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if url.startswith("http") else f"https://{url}")
            domain = parsed.netloc or parsed.path
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            # Remove linkedin.com domains (not useful for email)
            if "linkedin.com" in domain:
                return None
            return domain or None
        except Exception:
            return None


# Convenience function for one-off processing
async def scrape_linkedin_group(
    member_urls: list[str],
    rapidapi_key: str,
    email_verifier,
) -> list[EnrichedMember]:
    """
    Convenience function to scrape and enrich LinkedIn group members.

    Example:
        # Get member URLs from PhantomBuster export
        urls = ["https://linkedin.com/in/johndoe", ...]

        results = await scrape_linkedin_group(
            member_urls=urls,
            rapidapi_key="your-key",
            email_verifier=your_verifier,
        )

        for member in results:
            print(f"{member.full_name}: {member.email}")
    """
    service = LinkedInGroupScraperService(
        rapidapi_key=rapidapi_key,
        email_verifier=email_verifier,
    )

    results = []
    async for member in service.process_member_urls(member_urls):
        results.append(member)

    return results
