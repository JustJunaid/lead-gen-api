"""Async job status endpoints."""

import csv
import io
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from leadgen.api.deps import get_db
from leadgen.schemas.job import JobResponse, JobListResponse
from leadgen.repositories.job_repo import JobRepository
from leadgen.models.job import JobStatus

router = APIRouter()


@router.get("", response_model=JobListResponse)
async def list_jobs(
    page: int = 1,
    per_page: int = 20,
    status: str | None = None,
    job_type: str | None = None,
    db=Depends(get_db),
) -> JobListResponse:
    """List all async jobs with pagination and filtering."""
    repo = JobRepository(db)
    jobs, total = await repo.list_jobs(
        page=page,
        per_page=per_page,
        status=status,
        job_type=job_type,
    )
    return JobListResponse(
        items=jobs,
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db=Depends(get_db),
) -> JobResponse:
    """Get job status and details."""
    repo = JobRepository(db)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return job


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: UUID,
    db=Depends(get_db),
) -> dict:
    """Cancel a running job."""
    repo = JobRepository(db)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    cancelled = await repo.cancel(job_id)
    return {"success": cancelled, "job_id": str(job_id)}


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: UUID,
    db=Depends(get_db),
) -> dict:
    """Retry failed tasks in a job."""
    repo = JobRepository(db)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    retried_count = await repo.retry_failed_tasks(job_id)
    return {"success": True, "retried_tasks": retried_count, "job_id": str(job_id)}


@router.get("/{job_id}/export")
async def export_job_results(
    job_id: UUID,
    format: Literal["csv", "json"] = "csv",
    db=Depends(get_db),
):
    """
    Export job results as CSV or JSON.

    ## Usage

    After a job completes, use this endpoint to download the enriched data.

    - **CSV**: Download as spreadsheet-compatible file
    - **JSON**: Download as JSON array

    ## CSV Columns

    - first_name, last_name, full_name
    - email, email_verified
    - job_title, company_name, company_domain
    - linkedin_url, location

    ## Example

    ```bash
    curl -O "http://localhost:8000/api/v1/jobs/{job_id}/export?format=csv"
    ```
    """
    repo = JobRepository(db)
    job = await repo.get(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is not completed. Current status: {job.status}",
        )

    # Get results from job
    result = job.result or {}
    profiles = result.get("profiles", [])

    if not profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No results found for this job",
        )

    if format == "json":
        return {
            "job_id": str(job_id),
            "total": len(profiles),
            "profiles": profiles,
        }

    # Generate CSV
    csv_columns = [
        "first_name",
        "last_name",
        "full_name",
        "email",
        "email_verified",
        "job_title",
        "company_name",
        "company_domain",
        "linkedin_url",
        "location",
    ]

    def generate_csv():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=csv_columns, extrasaction="ignore")
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for profile in profiles:
            writer.writerow(profile)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"enriched_leads_{job_id}.csv"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
