"""Company domain finder service using MX record lookup."""

import asyncio
import dns.resolver
import re
from typing import Optional

import structlog

logger = structlog.get_logger()


class CompanyDomainFinder:
    """
    Find company email domain using heuristics and MX validation.

    This service attempts to find a valid email domain for a company
    without relying on external APIs. It uses:

    1. Company name normalization
    2. Common domain suffix attempts (.com, .io, .co)
    3. DNS MX record validation

    Usage:
        finder = CompanyDomainFinder()
        domain = await finder.find_domain("Acme Corporation")
        # Returns: "acme.com" if valid, None otherwise
    """

    # Common domain suffixes to try, in order of likelihood
    DOMAIN_SUFFIXES = [".com", ".io", ".co", ".net", ".org", ".ai", ".dev"]

    # Words to remove from company names
    NOISE_WORDS = [
        "inc", "inc.", "incorporated", "corp", "corp.", "corporation",
        "llc", "llc.", "ltd", "ltd.", "limited", "co", "co.",
        "company", "companies", "group", "holdings", "plc",
        "the", "and", "&", "technologies", "technology", "tech",
        "solutions", "services", "consulting", "partners", "labs",
    ]

    def __init__(self, cache: dict | None = None):
        """
        Initialize domain finder.

        Args:
            cache: Optional dict to use as cache (for Redis integration later)
        """
        self._cache = cache if cache is not None else {}
        self._resolver = dns.resolver.Resolver()
        self._resolver.timeout = 3.0
        self._resolver.lifetime = 5.0

    async def find_domain(self, company_name: str) -> Optional[str]:
        """
        Find a valid email domain for a company.

        Args:
            company_name: Company name (e.g., "Acme Corporation")

        Returns:
            Valid domain (e.g., "acme.com") or None if not found
        """
        if not company_name or not company_name.strip():
            return None

        # Check cache first
        cache_key = company_name.lower().strip()
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug("Domain cache hit", company=company_name, domain=cached)
            return cached

        # Normalize company name to potential domain base
        domain_bases = self._normalize_company_name(company_name)

        if not domain_bases:
            logger.debug("Could not normalize company name", company=company_name)
            self._cache[cache_key] = None
            return None

        # Try each base with each suffix
        for base in domain_bases:
            for suffix in self.DOMAIN_SUFFIXES:
                domain = f"{base}{suffix}"
                if await self._has_valid_mx(domain):
                    logger.info(
                        "Found valid domain",
                        company=company_name,
                        domain=domain,
                    )
                    self._cache[cache_key] = domain
                    return domain

        # No valid domain found
        logger.debug("No valid domain found", company=company_name, tried=domain_bases)
        self._cache[cache_key] = None
        return None

    def _normalize_company_name(self, name: str) -> list[str]:
        """
        Normalize company name to potential domain bases.

        Examples:
            "Acme Corporation" → ["acme"]
            "The Widget Co." → ["widget"]
            "OpenAI" → ["openai"]
            "Johnson & Johnson" → ["johnsonjohnson", "johnson"]

        Returns:
            List of potential domain bases to try
        """
        # Lowercase and strip
        name = name.lower().strip()

        # Remove noise words
        words = name.split()
        filtered_words = [
            w for w in words
            if w.lower() not in self.NOISE_WORDS
        ]

        if not filtered_words:
            # All words were noise, try original
            filtered_words = words

        # Generate variations
        bases = []

        # Try all words concatenated (johnsonjohnson)
        if filtered_words:
            concatenated = "".join(self._clean_word(w) for w in filtered_words)
            if concatenated and len(concatenated) >= 3:
                bases.append(concatenated)

        # Try first word only (johnson)
        if filtered_words:
            first_word = self._clean_word(filtered_words[0])
            if first_word and len(first_word) >= 3 and first_word not in bases:
                bases.append(first_word)

        # Try first two words concatenated (if different from above)
        if len(filtered_words) >= 2:
            two_words = self._clean_word(filtered_words[0]) + self._clean_word(filtered_words[1])
            if two_words and two_words not in bases:
                bases.append(two_words)

        return bases

    def _clean_word(self, word: str) -> str:
        """Remove non-alphanumeric characters from word."""
        return re.sub(r"[^a-z0-9]", "", word.lower())

    async def _has_valid_mx(self, domain: str) -> bool:
        """
        Check if domain has valid MX records.

        Args:
            domain: Domain to check (e.g., "acme.com")

        Returns:
            True if domain has MX records, False otherwise
        """
        try:
            # Run DNS lookup in thread pool (dns.resolver is blocking)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._resolver.resolve(domain, "MX"),
            )
            return True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return False
        except dns.exception.Timeout:
            logger.warning("DNS timeout", domain=domain)
            return False
        except Exception as e:
            logger.warning("DNS lookup error", domain=domain, error=str(e))
            return False

    def clear_cache(self) -> None:
        """Clear the domain cache."""
        self._cache.clear()

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        total = len(self._cache)
        found = sum(1 for v in self._cache.values() if v is not None)
        return {
            "total_entries": total,
            "domains_found": found,
            "domains_not_found": total - found,
        }
