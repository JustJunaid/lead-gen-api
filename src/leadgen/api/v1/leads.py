"""Lead CRUD endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from leadgen.api.deps import get_db
from leadgen.models.lead import LeadStatus, DataSource
from leadgen.schemas.lead import (
    LeadCreate,
    LeadUpdate,
    LeadResponse,
    LeadListResponse,
    LeadSummary,
    LeadBatchCreate,
    LeadBatchResponse,
)
from leadgen.repositories.lead_repo import LeadRepository

router = APIRouter()


@router.get("", response_model=LeadListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: list[LeadStatus] | None = Query(None),
    source: list[DataSource] | None = Query(None),
    company_domain: str | None = None,
    seniority_level: list[str] | None = Query(None),
    has_email: bool | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db=Depends(get_db),
) -> LeadListResponse:
    """List leads with filtering and pagination."""
    repo = LeadRepository(db)
    leads, total = await repo.list_leads(
        page=page,
        per_page=per_page,
        status=status,
        source=source,
        company_domain=company_domain,
        seniority_level=seniority_level,
        has_email=has_email,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    # Convert to summary format
    items = []
    for lead in leads:
        primary_email = None
        if lead.emails:
            for email in lead.emails:
                if email.is_primary:
                    primary_email = email.email
                    break
            if not primary_email:
                primary_email = lead.emails[0].email if lead.emails else None

        items.append(
            LeadSummary(
                id=lead.id,
                full_name=lead.full_name,
                job_title=lead.job_title,
                linkedin_url=lead.linkedin_url,
                status=lead.status,
                source=lead.source,
                company_name=lead.company.name if lead.company else None,
                primary_email=primary_email,
                created_at=lead.created_at,
            )
        )

    return LeadListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page if total > 0 else 0,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: UUID,
    db=Depends(get_db),
) -> LeadResponse:
    """Get a single lead by ID."""
    repo = LeadRepository(db)
    lead = await repo.get(lead_id)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    return LeadResponse.model_validate(lead)


@router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    data: LeadCreate,
    db=Depends(get_db),
) -> LeadResponse:
    """Create a new lead."""
    repo = LeadRepository(db)

    # Check for duplicates
    if data.linkedin_url:
        existing = await repo.get_by_linkedin_url(data.linkedin_url)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lead with LinkedIn URL {data.linkedin_url} already exists",
            )

    # Create lead
    lead = await repo.create(
        first_name=data.first_name,
        last_name=data.last_name,
        full_name=data.full_name,
        job_title=data.job_title,
        seniority_level=data.seniority_level,
        department=data.department,
        linkedin_url=data.linkedin_url,
        linkedin_username=data.linkedin_username,
        personal_city=data.personal_city,
        personal_state=data.personal_state,
        personal_country=data.personal_country,
        source=data.source,
        company_id=data.company_id,
    )

    # Add email if provided
    if data.email:
        await repo.add_email(lead.id, str(data.email), is_primary=True)

    # Refresh to get relationships
    lead = await repo.get(lead.id)

    return LeadResponse.model_validate(lead)


@router.post("/batch", response_model=LeadBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_leads_batch(
    data: LeadBatchCreate,
    db=Depends(get_db),
) -> LeadBatchResponse:
    """Create multiple leads at once."""
    repo = LeadRepository(db)

    created = 0
    duplicates = 0
    errors = []

    for idx, lead_data in enumerate(data.leads):
        try:
            # Check for duplicates if deduplication is enabled
            if data.deduplicate and lead_data.linkedin_url:
                existing = await repo.get_by_linkedin_url(lead_data.linkedin_url)
                if existing:
                    duplicates += 1
                    continue

            # Create lead
            lead = await repo.create(
                first_name=lead_data.first_name,
                last_name=lead_data.last_name,
                full_name=lead_data.full_name,
                job_title=lead_data.job_title,
                seniority_level=lead_data.seniority_level,
                department=lead_data.department,
                linkedin_url=lead_data.linkedin_url,
                linkedin_username=lead_data.linkedin_username,
                personal_city=lead_data.personal_city,
                personal_state=lead_data.personal_state,
                personal_country=lead_data.personal_country,
                source=lead_data.source,
                company_id=lead_data.company_id,
            )

            # Add email if provided
            if lead_data.email:
                await repo.add_email(lead.id, str(lead_data.email), is_primary=True)

            created += 1

        except Exception as e:
            errors.append({"index": idx, "error": str(e)})

    return LeadBatchResponse(
        created=created,
        duplicates=duplicates,
        errors=errors,
    )


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: UUID,
    data: LeadUpdate,
    db=Depends(get_db),
) -> LeadResponse:
    """Update a lead."""
    repo = LeadRepository(db)

    # Get non-None fields only
    update_data = data.model_dump(exclude_unset=True, exclude_none=True)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    lead = await repo.update(lead_id, **update_data)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    return LeadResponse.model_validate(lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: UUID,
    db=Depends(get_db),
) -> None:
    """Delete a lead."""
    repo = LeadRepository(db)
    deleted = await repo.delete(lead_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )


@router.post("/{lead_id}/emails", response_model=LeadResponse)
async def add_email_to_lead(
    lead_id: UUID,
    email: str,
    email_type: str | None = None,
    is_primary: bool = False,
    db=Depends(get_db),
) -> LeadResponse:
    """Add an email to a lead."""
    repo = LeadRepository(db)

    email_obj = await repo.add_email(lead_id, email, email_type=email_type, is_primary=is_primary)

    if not email_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    lead = await repo.get(lead_id)
    return LeadResponse.model_validate(lead)
