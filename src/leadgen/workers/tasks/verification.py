"""Verification tasks for Celery — batch email finding and verification."""

import asyncio
from typing import Any

from celery import shared_task
import structlog

from leadgen.workers.celery_app import celery_app

logger = structlog.get_logger()


def run_async(coro):
    """Run async function in sync context for Celery."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(bind=True)
def verify_leads_batch(self, job_id: str):
    """
    Process a batch of leads: generate email permutations and verify.

    Domain-level optimizations:
    - Groups leads by domain to reduce redundant API calls
    - If a pattern works for one person at a domain, tries it first for others
    - If domain is catch-all, stops after first permutation per lead
    - Skips domains with no MX records
    """
    from leadgen.config import settings
    from leadgen.models.database import async_session_maker
    from leadgen.repositories.job_repo import JobRepository
    from leadgen.models.job import JobStatus
    from leadgen.services.enrichment.email_verifier import (
        EmailPermutator,
        MailTesterNinjaVerifier,
        VerificationStatus,
    )

    async def _process_job():
        async with async_session_maker() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)

            if not job:
                print(f"[VERIFY-BATCH] Job not found: {job_id}", flush=True)
                return {"success": False, "error": "Job not found"}

            await job_repo.update_status(job_id, JobStatus.RUNNING)
            await session.commit()

            config = job.config or {}
            leads = config.get("leads", [])

            if not leads:
                await job_repo.update_status(job_id, JobStatus.FAILED, error_message="No leads provided")
                await session.commit()
                return {"success": False, "error": "No leads provided"}

            if not settings.mailtester_ninja_api_key:
                await job_repo.update_status(job_id, JobStatus.FAILED, error_message="MailTester.ninja API key not configured")
                await session.commit()
                return {"success": False, "error": "API key not configured"}

            permutator = EmailPermutator()
            verifier = MailTesterNinjaVerifier(
                api_key=settings.mailtester_ninja_api_key.get_secret_value(),
                timeout=settings.email_verification_timeout,
            )

            try:
                verified_leads = []
                processed = 0
                failed = 0

                # Domain-level knowledge: track known patterns and catch-all domains
                domain_patterns: dict[str, str] = {}  # domain -> working pattern
                catch_all_domains: set[str] = set()
                dead_domains: set[str] = set()  # no MX records

                # Group leads by domain for smarter processing
                from collections import defaultdict
                domain_groups: dict[str, list[dict]] = defaultdict(list)
                for lead in leads:
                    domain = lead["website"].strip().lower()
                    domain = domain.removeprefix("https://").removeprefix("http://")
                    domain = domain.removeprefix("www.")
                    domain = domain.rstrip("/")
                    lead["_domain"] = domain
                    domain_groups[domain].append(lead)

                print(f"[VERIFY-BATCH] Processing {len(leads)} leads across {len(domain_groups)} domains", flush=True)

                for domain, domain_leads in domain_groups.items():
                    print(f"[VERIFY-BATCH] Domain: {domain} ({len(domain_leads)} leads)", flush=True)

                    for lead in domain_leads:
                        domain = lead["_domain"]

                        # Skip dead domains
                        if domain in dead_domains:
                            print(f"[VERIFY-BATCH]   Skipping {lead['first_name']} {lead['last_name']} - dead domain", flush=True)
                            failed += 1
                            processed += 1
                            continue

                        # Generate permutations
                        permutations = permutator.generate(
                            first_name=lead["first_name"],
                            last_name=lead["last_name"],
                            domain=domain,
                        )

                        if not permutations:
                            failed += 1
                            processed += 1
                            continue

                        # If we know the working pattern for this domain, try it first
                        if domain in domain_patterns:
                            known_pattern = domain_patterns[domain]
                            known_email = permutator._apply_pattern(
                                known_pattern,
                                lead["first_name"].lower().strip(),
                                lead["last_name"].lower().strip(),
                                domain,
                            )
                            if known_email and known_email in permutations:
                                # Move known pattern to front
                                permutations.remove(known_email)
                                permutations.insert(0, known_email)

                        # If domain is catch-all, only try first permutation
                        if domain in catch_all_domains:
                            permutations = permutations[:1]

                        # Verify permutations
                        found = False
                        for email in permutations:
                            result = await verifier.verify(email)

                            if result.status == VerificationStatus.VALID:
                                verified_leads.append({
                                    "first_name": lead["first_name"],
                                    "last_name": lead["last_name"],
                                    "website": lead["website"],
                                    "email": email,
                                })
                                found = True

                                # Learn the pattern for this domain
                                pattern = permutator.detect_pattern(
                                    email, lead["first_name"], lead["last_name"]
                                )
                                if pattern:
                                    domain_patterns[domain] = pattern
                                    print(f"[VERIFY-BATCH]   Learned pattern for {domain}: {pattern}", flush=True)
                                break

                            if result.status == VerificationStatus.CATCH_ALL:
                                catch_all_domains.add(domain)
                                print(f"[VERIFY-BATCH]   {domain} is catch-all, skipping remaining permutations", flush=True)
                                break

                            if result.status == VerificationStatus.INVALID and result.reason and "No MX" in result.reason:
                                dead_domains.add(domain)
                                print(f"[VERIFY-BATCH]   {domain} has no MX records, skipping domain", flush=True)
                                break

                        if not found:
                            failed += 1

                        processed += 1

                        # Update progress every 10 leads
                        if processed % 10 == 0:
                            await job_repo.update_progress(
                                job_id,
                                processed_items=processed,
                                failed_items=failed,
                            )
                            await session.commit()
                            print(f"[VERIFY-BATCH]   Progress: {processed}/{len(leads)} ({len(verified_leads)} verified)", flush=True)

                # Final update
                await job_repo.update_status(
                    job_id,
                    JobStatus.COMPLETED,
                    result={"verified_leads": verified_leads},
                )
                await job_repo.update_progress(
                    job_id,
                    processed_items=processed,
                    failed_items=failed,
                )
                await session.commit()

                print(f"[VERIFY-BATCH] Completed: {processed} processed, {len(verified_leads)} verified, {failed} failed", flush=True)
                print(f"[VERIFY-BATCH] Domain stats: {len(catch_all_domains)} catch-all, {len(dead_domains)} dead, {len(domain_patterns)} patterns learned", flush=True)

                # Send webhook if configured
                webhook_url = config.get("webhook_url") or job.webhook_url
                if webhook_url:
                    await _send_webhook(webhook_url, {
                        "job_id": str(job_id),
                        "status": "completed",
                        "total_input": len(leads),
                        "total_verified": len(verified_leads),
                        "verified_leads": verified_leads,
                    })

                return {
                    "success": True,
                    "job_id": job_id,
                    "total_verified": len(verified_leads),
                    "processed": processed,
                    "failed": failed,
                }

            except Exception as e:
                print(f"[VERIFY-BATCH] Job failed: {e}", flush=True)
                await job_repo.update_status(job_id, JobStatus.FAILED, error_message=str(e))
                await session.commit()
                raise

            finally:
                await verifier.close()

    return run_async(_process_job())


@shared_task(bind=True)
def verify_emails_batch(self, job_id: str):
    """
    Verify a batch of email addresses directly via MailTester.ninja.
    """
    from leadgen.config import settings
    from leadgen.models.database import async_session_maker
    from leadgen.repositories.job_repo import JobRepository
    from leadgen.models.job import JobStatus
    from leadgen.services.enrichment.email_verifier import (
        MailTesterNinjaVerifier,
        VerificationStatus,
    )

    async def _process_job():
        async with async_session_maker() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)

            if not job:
                print(f"[VERIFY-EMAIL-BATCH] Job not found: {job_id}", flush=True)
                return {"success": False, "error": "Job not found"}

            await job_repo.update_status(job_id, JobStatus.RUNNING)
            await session.commit()

            config = job.config or {}
            emails = config.get("emails", [])

            if not emails:
                await job_repo.update_status(job_id, JobStatus.FAILED, error_message="No emails provided")
                await session.commit()
                return {"success": False, "error": "No emails provided"}

            if not settings.mailtester_ninja_api_key:
                await job_repo.update_status(job_id, JobStatus.FAILED, error_message="MailTester.ninja API key not configured")
                await session.commit()
                return {"success": False, "error": "API key not configured"}

            verifier = MailTesterNinjaVerifier(
                api_key=settings.mailtester_ninja_api_key.get_secret_value(),
                timeout=settings.email_verification_timeout,
            )

            try:
                results = []
                processed = 0
                failed = 0

                print(f"[VERIFY-EMAIL-BATCH] Verifying {len(emails)} emails", flush=True)

                for email in emails:
                    result = await verifier.verify(email)

                    results.append({
                        "email": email,
                        "status": result.status.value,
                        "is_deliverable": result.is_deliverable,
                        "is_catch_all": result.is_catch_all,
                        "mx_found": result.mx_found,
                        "reason": result.reason,
                    })

                    if result.status == VerificationStatus.VALID:
                        processed += 1
                    else:
                        failed += 1

                    # Update progress every 10 emails
                    total_done = processed + failed
                    if total_done % 10 == 0:
                        await job_repo.update_progress(
                            job_id,
                            processed_items=total_done,
                            failed_items=failed,
                        )
                        await session.commit()
                        print(f"[VERIFY-EMAIL-BATCH]   Progress: {total_done}/{len(emails)}", flush=True)

                # Final update
                await job_repo.update_status(
                    job_id,
                    JobStatus.COMPLETED,
                    result={"results": results},
                )
                await job_repo.update_progress(
                    job_id,
                    processed_items=processed + failed,
                    failed_items=failed,
                )
                await session.commit()

                print(f"[VERIFY-EMAIL-BATCH] Completed: {processed} valid, {failed} invalid/unknown", flush=True)

                # Send webhook if configured
                webhook_url = config.get("webhook_url") or job.webhook_url
                if webhook_url:
                    await _send_webhook(webhook_url, {
                        "job_id": str(job_id),
                        "status": "completed",
                        "total_emails": len(emails),
                        "total_valid": processed,
                        "results": results,
                    })

                return {
                    "success": True,
                    "job_id": job_id,
                    "total_valid": processed,
                    "total_invalid": failed,
                }

            except Exception as e:
                print(f"[VERIFY-EMAIL-BATCH] Job failed: {e}", flush=True)
                await job_repo.update_status(job_id, JobStatus.FAILED, error_message=str(e))
                await session.commit()
                raise

            finally:
                await verifier.close()

    return run_async(_process_job())


async def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    """Send webhook notification."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            print(f"[WEBHOOK] Sent to {url}, status={response.status_code}", flush=True)
    except Exception as e:
        print(f"[WEBHOOK] Failed for {url}: {e}", flush=True)
