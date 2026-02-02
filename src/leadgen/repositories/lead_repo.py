"""Lead repository for data access."""

from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leadgen.models.lead import Lead, LeadStatus, DataSource
from leadgen.models.company import Company
from leadgen.models.email import Email


class LeadRepository:
    """Repository for Lead CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, lead_id: UUID) -> Lead | None:
        """Get a lead by ID with relationships."""
        result = await self.db.execute(
            select(Lead)
            .options(selectinload(Lead.company), selectinload(Lead.emails))
            .where(Lead.id == lead_id)
        )
        return result.scalar_one_or_none()

    async def get_by_linkedin_url(self, linkedin_url: str) -> Lead | None:
        """Get a lead by LinkedIn URL."""
        result = await self.db.execute(
            select(Lead).where(Lead.linkedin_url == linkedin_url)
        )
        return result.scalar_one_or_none()

    async def list_leads(
        self,
        page: int = 1,
        per_page: int = 20,
        status: list[LeadStatus] | None = None,
        source: list[DataSource] | None = None,
        company_domain: str | None = None,
        seniority_level: list[str] | None = None,
        has_email: bool | None = None,
        email_verified: bool | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[Lead], int]:
        """List leads with filtering and pagination."""
        # Base query
        query = select(Lead).options(selectinload(Lead.company), selectinload(Lead.emails))

        # Apply filters
        conditions = []

        if status:
            conditions.append(Lead.status.in_(status))

        if source:
            conditions.append(Lead.source.in_(source))

        if company_domain:
            query = query.join(Lead.company)
            conditions.append(Company.domain == company_domain)

        if seniority_level:
            conditions.append(Lead.seniority_level.in_(seniority_level))

        if has_email is not None:
            if has_email:
                query = query.join(Lead.emails)
            else:
                query = query.outerjoin(Lead.emails).where(Email.id.is_(None))

        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Lead.full_name.ilike(search_term),
                    Lead.job_title.ilike(search_term),
                    Lead.linkedin_url.ilike(search_term),
                )
            )

        if conditions:
            query = query.where(*conditions)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Apply sorting
        sort_column = getattr(Lead, sort_by, Lead.created_at)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        result = await self.db.execute(query)
        leads = list(result.scalars().unique().all())

        return leads, total

    async def create(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        full_name: str | None = None,
        job_title: str | None = None,
        linkedin_url: str | None = None,
        source: DataSource = DataSource.API,
        company_id: UUID | None = None,
        **kwargs,
    ) -> Lead:
        """Create a new lead."""
        # Auto-generate full_name if not provided
        if not full_name and (first_name or last_name):
            full_name = f"{first_name or ''} {last_name or ''}".strip()

        lead = Lead(
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            job_title=job_title,
            linkedin_url=linkedin_url,
            source=source,
            company_id=company_id,
            status=LeadStatus.NEW,
            **kwargs,
        )

        self.db.add(lead)
        await self.db.flush()
        await self.db.refresh(lead)

        return lead

    async def update(self, lead_id: UUID, **kwargs) -> Lead | None:
        """Update a lead."""
        lead = await self.get(lead_id)
        if not lead:
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(lead, key):
                setattr(lead, key, value)

        await self.db.flush()
        await self.db.refresh(lead)

        return lead

    async def delete(self, lead_id: UUID) -> bool:
        """Delete a lead."""
        lead = await self.get(lead_id)
        if not lead:
            return False

        await self.db.delete(lead)
        await self.db.flush()

        return True

    async def add_email(
        self,
        lead_id: UUID,
        email: str,
        email_type: str | None = None,
        is_primary: bool = False,
    ) -> Email | None:
        """Add an email to a lead."""
        lead = await self.get(lead_id)
        if not lead:
            return None

        email_obj = Email(
            lead_id=lead_id,
            email=email,
            email_type=email_type,
            is_primary=is_primary,
        )

        self.db.add(email_obj)
        await self.db.flush()

        return email_obj

    async def find_duplicates(self, linkedin_url: str | None = None, email: str | None = None) -> list[Lead]:
        """Find potential duplicate leads."""
        conditions = []

        if linkedin_url:
            conditions.append(Lead.linkedin_url == linkedin_url)

        if email:
            # Check if email exists
            subquery = select(Email.lead_id).where(Email.email == email)
            conditions.append(Lead.id.in_(subquery))

        if not conditions:
            return []

        result = await self.db.execute(
            select(Lead).where(or_(*conditions))
        )

        return list(result.scalars().all())
