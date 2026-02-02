"""Email verification service using MailTester.ninja API."""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import httpx
import structlog

logger = structlog.get_logger()


class VerificationStatus(str, Enum):
    """Email verification status."""

    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    UNKNOWN = "unknown"
    PENDING = "pending"


@dataclass
class VerificationResult:
    """Result of email verification."""

    email: str
    status: VerificationStatus
    is_deliverable: bool = False
    is_catch_all: bool = False
    is_disposable: bool = False
    mx_found: bool = False
    reason: str | None = None
    is_rate_limited: bool = False


class EmailVerifierProtocol(Protocol):
    """Protocol for email verification services."""

    async def verify(self, email: str) -> VerificationResult:
        """Verify a single email address."""
        ...

    async def verify_batch(self, emails: list[str]) -> list[VerificationResult]:
        """Verify multiple email addresses."""
        ...


class MailTesterNinjaVerifier:
    """
    Email verifier using MailTester.ninja API directly.

    API Documentation: https://mailtester.ninja/api/

    Rate Limits (Pro Plan):
    - 35 emails per 30 seconds
    - Uses sliding window rate limiting
    """

    VERIFY_URL = "https://happy.mailtester.ninja/ninja"

    # Rate limiting: 35 emails per 30 seconds
    RATE_LIMIT_MAX_REQUESTS = 35
    RATE_LIMIT_WINDOW_MS = 30 * 1000  # 30 seconds

    # Retry config for 429 errors
    MAX_RETRIES = 2
    BASE_RETRY_DELAY_MS = 31000  # 31 seconds (just over the rate limit window)

    def __init__(
        self,
        api_key: str,
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._request_timestamps: list[float] = []

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect rate limits using sliding window."""
        now = time.time() * 1000  # Convert to milliseconds

        # Remove timestamps older than the rate limit window
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if now - ts < self.RATE_LIMIT_WINDOW_MS
        ]

        # If we've hit the limit, wait until the oldest request expires
        if len(self._request_timestamps) >= self.RATE_LIMIT_MAX_REQUESTS:
            oldest_timestamp = self._request_timestamps[0]
            wait_time_ms = self.RATE_LIMIT_WINDOW_MS - (now - oldest_timestamp) + 100  # +100ms buffer

            if wait_time_ms > 0:
                wait_time_s = wait_time_ms / 1000
                logger.info(
                    "Rate limit reached, waiting",
                    current_requests=len(self._request_timestamps),
                    max_requests=self.RATE_LIMIT_MAX_REQUESTS,
                    wait_seconds=round(wait_time_s, 1),
                )
                await asyncio.sleep(wait_time_s)

                # Clean up again after waiting
                now = time.time() * 1000
                self._request_timestamps = [
                    ts for ts in self._request_timestamps
                    if now - ts < self.RATE_LIMIT_WINDOW_MS
                ]

        # Record this request
        self._request_timestamps.append(time.time() * 1000)

    async def verify(self, email: str) -> VerificationResult:
        """Verify a single email address."""
        client = await self._get_client()
        retry_count = 0

        while retry_count <= self.MAX_RETRIES:
            try:
                # Wait for rate limit before making request
                await self._wait_for_rate_limit()

                response = await client.get(
                    f"{self.VERIFY_URL}?email={email}&key={self.api_key}"
                )

                # Handle rate limit response
                if response.status_code == 429:
                    retry_count += 1
                    if retry_count <= self.MAX_RETRIES:
                        delay_ms = self.BASE_RETRY_DELAY_MS * (2 ** (retry_count - 1))
                        logger.warning(
                            "API rate limit hit",
                            email=email,
                            retry=retry_count,
                            max_retries=self.MAX_RETRIES,
                            delay_seconds=round(delay_ms / 1000, 1),
                        )
                        await asyncio.sleep(delay_ms / 1000)
                        continue
                    else:
                        return VerificationResult(
                            email=email,
                            status=VerificationStatus.UNKNOWN,
                            reason="Rate limit exceeded after maximum retries",
                            is_rate_limited=True,
                        )

                response.raise_for_status()
                data = response.json()

                return self._parse_response(email, data)

            except httpx.TimeoutException:
                logger.warning("Email verification timed out", email=email)
                return VerificationResult(
                    email=email,
                    status=VerificationStatus.INVALID,
                    reason="Email validation timed out",
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403):
                    logger.error("Authentication failed with MailTester.ninja")
                    return VerificationResult(
                        email=email,
                        status=VerificationStatus.UNKNOWN,
                        reason="Authentication failed with email validation service",
                    )
                logger.error("Email verification HTTP error", email=email, status=e.response.status_code)
                return VerificationResult(
                    email=email,
                    status=VerificationStatus.UNKNOWN,
                    reason=f"HTTP error: {e.response.status_code}",
                )
            except Exception as e:
                logger.error("Email verification error", email=email, error=str(e))
                return VerificationResult(
                    email=email,
                    status=VerificationStatus.UNKNOWN,
                    reason=str(e),
                )

        # Should not reach here, but just in case
        return VerificationResult(
            email=email,
            status=VerificationStatus.UNKNOWN,
            reason="Verification failed after retries",
        )

    def _parse_response(self, email: str, data: dict) -> VerificationResult:
        """
        Parse MailTester.ninja API response.

        API Response format:
        {
            "email": "john.doe@email.com",
            "user": "John Doe",
            "domain": "email.com",
            "mx": "mx.sender-email.com",
            "code": "ok",           # ok=valid, ko=invalid, mb=unverifiable
            "message": "Accepted",  # Accepted|Limited|Rejected|Catch-All|No Mx|Mx Error|Timeout|SPAM Block
            "connections": 1
        }
        """
        code = (data.get("code") or "").lower()
        message = (data.get("message") or "")
        message_lower = message.lower()
        mx = data.get("mx")

        # code "ok" with message "Accepted" = Valid email
        if code == "ok" and message_lower == "accepted":
            return VerificationResult(
                email=email,
                status=VerificationStatus.VALID,
                is_deliverable=True,
                mx_found=bool(mx),
            )

        # code "ok" with message "Limited" = Valid but rate-limited inbox
        if code == "ok" and message_lower == "limited":
            return VerificationResult(
                email=email,
                status=VerificationStatus.VALID,
                is_deliverable=True,
                mx_found=bool(mx),
                reason="Valid but inbox has rate limits",
            )

        # Catch-All domains - message "Catch-All"
        # These accept any email but may not actually deliver
        if message_lower == "catch-all":
            return VerificationResult(
                email=email,
                status=VerificationStatus.CATCH_ALL,
                is_deliverable=True,
                is_catch_all=True,
                mx_found=bool(mx),
                reason="Catch-all domain - email may or may not exist",
            )

        # code "mb" = Unverifiable (mailbox exists but can't confirm)
        # This is different from catch-all - the server won't tell us
        if code == "mb":
            return VerificationResult(
                email=email,
                status=VerificationStatus.CATCH_ALL,
                is_deliverable=True,
                is_catch_all=True,
                mx_found=bool(mx),
                reason="Unverifiable - server won't confirm mailbox existence",
            )

        # code "ko" with message "Rejected" = Invalid email
        if code == "ko" or message_lower == "rejected":
            return VerificationResult(
                email=email,
                status=VerificationStatus.INVALID,
                reason="Email rejected by mail server",
                mx_found=bool(mx),
            )

        # No MX records found
        if message_lower == "no mx":
            return VerificationResult(
                email=email,
                status=VerificationStatus.INVALID,
                reason="No MX records found for domain",
                mx_found=False,
            )

        # MX Error - can't connect to mail server
        if message_lower == "mx error":
            return VerificationResult(
                email=email,
                status=VerificationStatus.UNKNOWN,
                reason="Could not connect to mail server",
                mx_found=bool(mx),
            )

        # Timeout - server didn't respond in time
        if message_lower == "timeout":
            return VerificationResult(
                email=email,
                status=VerificationStatus.UNKNOWN,
                reason="Mail server timeout",
                mx_found=bool(mx),
            )

        # SPAM Block - our IP is blocked
        if message_lower == "spam block":
            return VerificationResult(
                email=email,
                status=VerificationStatus.UNKNOWN,
                reason="Verification blocked by spam filter",
                mx_found=bool(mx),
            )

        # Fallback: check for missing MX
        if not mx or mx == "" or mx == "null":
            return VerificationResult(
                email=email,
                status=VerificationStatus.INVALID,
                reason="No MX records found for domain",
                mx_found=False,
            )

        # If code is "ok" but message isn't recognized, still treat as valid
        if code == "ok":
            return VerificationResult(
                email=email,
                status=VerificationStatus.VALID,
                is_deliverable=True,
                mx_found=bool(mx),
                reason=message if message else None,
            )

        # Default: unknown status
        return VerificationResult(
            email=email,
            status=VerificationStatus.UNKNOWN,
            reason=message or f"Unknown response: code={code}",
            mx_found=bool(mx),
        )

    async def verify_batch(self, emails: list[str]) -> list[VerificationResult]:
        """
        Verify multiple emails sequentially with rate limiting.

        MailTester.ninja Pro Plan: 35 emails per 30 seconds
        Rate limiting is handled automatically by verify().
        """
        results = []

        for i, email in enumerate(emails):
            result = await self.verify(email)
            results.append(result)

            # Log progress every 10 emails
            if (i + 1) % 10 == 0 or i == len(emails) - 1:
                valid_count = sum(1 for r in results if r.status == VerificationStatus.VALID)
                logger.info(
                    "Verification progress",
                    completed=i + 1,
                    total=len(emails),
                    valid=valid_count,
                )

        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class EmailPermutator:
    """Generate email permutations based on name and domain."""

    COMMON_PATTERNS = [
        "{first}.{last}",      # john.smith@  (~50% of companies)
        "{f}{last}",           # jsmith@
        "{f}.{last}",          # j.smith@
        "{first}",             # john@
        "{first}{last}",       # johnsmith@
        "{first}_{last}",      # john_smith@
        "{first}{l}",          # johns@
        "{last}.{first}",      # smith.john@
    ]

    def __init__(self, known_patterns: dict[str, str] | None = None):
        """
        Initialize permutator.

        Args:
            known_patterns: Dict of domain -> pattern that works for that domain
        """
        self.known_patterns = known_patterns or {}

    def generate(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        max_permutations: int = 13,
    ) -> list[str]:
        """
        Generate email permutations for a person.

        Args:
            first_name: Person's first name
            last_name: Person's last name
            domain: Company email domain
            max_permutations: Maximum permutations to generate

        Returns:
            List of possible email addresses, ordered by likelihood
        """
        first = first_name.lower().strip()
        last = last_name.lower().strip()

        # Handle special characters in names
        first = self._normalize_name(first)
        last = self._normalize_name(last)

        if not first or not last or not domain:
            return []

        permutations = []

        # If we know the pattern for this domain, put it first
        if domain in self.known_patterns:
            known_pattern = self.known_patterns[domain]
            email = self._apply_pattern(known_pattern, first, last, domain)
            if email:
                permutations.append(email)

        # Generate all other patterns
        for pattern in self.COMMON_PATTERNS:
            email = self._apply_pattern(pattern, first, last, domain)
            if email and email not in permutations:
                permutations.append(email)

        return permutations[:max_permutations]

    def _normalize_name(self, name: str) -> str:
        """Normalize name for email generation."""
        # Remove common suffixes/titles
        for suffix in [" jr", " sr", " iii", " ii", " iv"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]

        # Remove special characters but keep hyphens
        cleaned = ""
        for char in name:
            if char.isalpha() or char == "-":
                cleaned += char
            elif char == " ":
                cleaned += "-"  # Replace space with hyphen

        return cleaned.strip("-")

    def _apply_pattern(
        self,
        pattern: str,
        first: str,
        last: str,
        domain: str,
    ) -> str | None:
        """Apply a pattern to generate an email."""
        try:
            local_part = pattern.format(
                first=first,
                last=last,
                f=first[0] if first else "",
                l=last[0] if last else "",
            )
            return f"{local_part}@{domain}"
        except (IndexError, KeyError):
            return None

    def detect_pattern(self, email: str, first_name: str, last_name: str) -> str | None:
        """
        Detect the pattern used for an existing email.

        This helps build the known_patterns dict.
        """
        first = first_name.lower().strip()
        last = last_name.lower().strip()
        first = self._normalize_name(first)
        last = self._normalize_name(last)

        local_part = email.split("@")[0].lower()

        for pattern in self.COMMON_PATTERNS:
            expected = pattern.format(
                first=first,
                last=last,
                f=first[0] if first else "",
                l=last[0] if last else "",
            )
            if local_part == expected:
                return pattern

        return None
