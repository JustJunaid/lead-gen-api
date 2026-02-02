"""Scraping tasks for Celery."""

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


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def scrape_single_profile(self, job_task_id: str, linkedin_url: str, provider: str = None):
    """Scrape a single LinkedIn profile."""
    from leadgen.config import settings
    from leadgen.services.scraping.group_scraper import LinkedInGroupScraperService
    from leadgen.services.enrichment import MailTesterNinjaVerifier

    async def _scrape():
        # Initialize services
        email_verifier = None
        if settings.mailtester_ninja_api_key:
            email_verifier = MailTesterNinjaVerifier(
                api_key=settings.mailtester_ninja_api_key.get_secret_value(),
                timeout=settings.email_verification_timeout,
            )

        # Initialize domain finder for fallback domain lookup
        from leadgen.services.enrichment import CompanyDomainFinder
        domain_finder = CompanyDomainFinder()

        scraper = LinkedInGroupScraperService(
            rapidapi_key=settings.rapidapi_key.get_secret_value() if settings.rapidapi_key else None,
            email_verifier=email_verifier,
            domain_finder=domain_finder,
        )

        try:
            result = await scraper._enrich_single_profile(linkedin_url)
            if email_verifier and result.company_domain:
                result = await scraper._find_email_for_profile(result)

            return {
                "success": True,
                "job_task_id": job_task_id,
                "data": {
                    "linkedin_url": result.linkedin_url,
                    "first_name": result.first_name,
                    "last_name": result.last_name,
                    "full_name": result.full_name,
                    "job_title": result.job_title,
                    "company_name": result.company_name,
                    "company_domain": result.company_domain,
                    "location": result.location,
                    "email": result.email,
                    "email_verified": result.email_verified,
                },
            }
        finally:
            if email_verifier:
                await email_verifier.close()

    return run_async(_scrape())


@shared_task(bind=True)
def scrape_batch_profiles(self, job_id: str):
    """
    Orchestrate bulk scraping job.

    This task:
    1. Loads job config from database
    2. Processes profiles in batches
    3. Updates job progress
    4. Sends webhook on completion
    """
    from leadgen.config import settings
    from leadgen.models.database import async_session_maker
    from leadgen.repositories.job_repo import JobRepository
    from leadgen.models.job import JobStatus
    from leadgen.services.scraping.group_scraper import LinkedInGroupScraperService
    from leadgen.services.enrichment import MailTesterNinjaVerifier

    async def _process_job():
        async with async_session_maker() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)

            if not job:
                logger.error("Job not found", job_id=job_id)
                return {"success": False, "error": "Job not found"}

            # Update status to processing
            await job_repo.update_status(job_id, JobStatus.PROCESSING)
            await session.commit()

            config = job.config or {}
            linkedin_urls = config.get("linkedin_urls") or config.get("member_urls", [])
            find_emails = config.get("find_emails", True)

            if not linkedin_urls:
                await job_repo.update_status(job_id, JobStatus.FAILED, error="No URLs provided")
                await session.commit()
                return {"success": False, "error": "No URLs provided"}

            # Initialize services
            email_verifier = None
            if find_emails and settings.mailtester_ninja_api_key:
                email_verifier = MailTesterNinjaVerifier(
                    api_key=settings.mailtester_ninja_api_key.get_secret_value(),
                    timeout=settings.email_verification_timeout,
                )

            # Initialize domain finder for fallback domain lookup
            from leadgen.services.enrichment import CompanyDomainFinder
            domain_finder = CompanyDomainFinder()

            scraper = LinkedInGroupScraperService(
                rapidapi_key=settings.rapidapi_key.get_secret_value() if settings.rapidapi_key else None,
                email_verifier=email_verifier,
                domain_finder=domain_finder,
            )

            try:
                results = []
                processed = 0
                failed = 0

                async for member in scraper.process_member_urls(
                    urls=linkedin_urls,
                    enrich_profiles=config.get("enrich_profiles", True),
                    find_emails=find_emails,
                ):
                    if member.first_name or member.email:
                        results.append({
                            "linkedin_url": member.linkedin_url,
                            "first_name": member.first_name,
                            "last_name": member.last_name,
                            "full_name": member.full_name,
                            "job_title": member.job_title,
                            "company_name": member.company_name,
                            "company_domain": member.company_domain,
                            "location": member.location,
                            "email": member.email,
                            "email_verified": member.email_verified,
                        })
                        processed += 1
                    else:
                        failed += 1

                    # Update progress periodically
                    if (processed + failed) % 50 == 0:
                        await job_repo.update_progress(
                            job_id,
                            processed_items=processed,
                            failed_items=failed,
                        )
                        await session.commit()

                # Final update
                await job_repo.update_status(
                    job_id,
                    JobStatus.COMPLETED,
                    result={"profiles": results},
                )
                await job_repo.update_progress(
                    job_id,
                    processed_items=processed,
                    failed_items=failed,
                )
                await session.commit()

                # Send webhook if configured
                webhook_url = config.get("webhook_url") or job.webhook_url
                if webhook_url:
                    await _send_webhook(webhook_url, {
                        "job_id": str(job_id),
                        "status": "completed",
                        "processed": processed,
                        "failed": failed,
                        "results": results,
                    })

                logger.info(
                    "Batch scraping completed",
                    job_id=job_id,
                    processed=processed,
                    failed=failed,
                )

                return {
                    "success": True,
                    "job_id": job_id,
                    "processed": processed,
                    "failed": failed,
                }

            except Exception as e:
                logger.error("Batch scraping failed", job_id=job_id, error=str(e))
                await job_repo.update_status(job_id, JobStatus.FAILED, error=str(e))
                await session.commit()
                raise

            finally:
                if email_verifier:
                    await email_verifier.close()

    return run_async(_process_job())


async def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    """Send webhook notification."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Webhook sent", url=url, status=response.status_code)
    except Exception as e:
        logger.error("Webhook failed", url=url, error=str(e))


@shared_task(bind=True)
def process_group_scrape_job(self, job_id: str):
    """
    Process a LinkedIn group scraping job.

    Alias for scrape_batch_profiles - same logic applies.
    """
    return scrape_batch_profiles(job_id)
