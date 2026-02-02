"""Job repository for data access."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leadgen.models.job import AsyncJob, JobTask, JobStatus, JobType


class JobRepository:
    """Repository for AsyncJob CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, job_id: UUID) -> AsyncJob | None:
        """Get a job by ID with tasks."""
        result = await self.db.execute(
            select(AsyncJob)
            .options(selectinload(AsyncJob.tasks))
            .where(AsyncJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        job_type: str | None = None,
        user_id: UUID | None = None,
    ) -> tuple[list[AsyncJob], int]:
        """List jobs with filtering and pagination."""
        query = select(AsyncJob)

        conditions = []
        if status:
            conditions.append(AsyncJob.status == JobStatus(status))
        if job_type:
            conditions.append(AsyncJob.job_type == JobType(job_type))
        if user_id:
            conditions.append(AsyncJob.user_id == user_id)

        if conditions:
            query = query.where(*conditions)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Apply ordering and pagination
        query = query.order_by(AsyncJob.created_at.desc())
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        result = await self.db.execute(query)
        jobs = list(result.scalars().all())

        return jobs, total

    async def create(
        self,
        user_id: UUID,
        job_type: JobType,
        config: dict,
        total_items: int = 0,
        priority: int = 5,
        webhook_url: str | None = None,
    ) -> AsyncJob:
        """Create a new job."""
        job = AsyncJob(
            user_id=user_id,
            job_type=job_type,
            config=config,
            total_items=total_items,
            priority=priority,
            webhook_url=webhook_url,
            status=JobStatus.PENDING,
        )

        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)

        return job

    async def update_status(
        self,
        job_id: UUID,
        status: JobStatus,
        error_message: str | None = None,
        result: dict | None = None,
    ) -> AsyncJob | None:
        """Update job status."""
        job = await self.get(job_id)
        if not job:
            return None

        job.status = status

        if status == JobStatus.RUNNING and not job.started_at:
            job.started_at = datetime.utcnow()
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            job.completed_at = datetime.utcnow()

        if error_message:
            job.error_message = error_message
        if result:
            job.result = result

        await self.db.flush()
        await self.db.refresh(job)

        return job

    async def update_progress(
        self,
        job_id: UUID,
        processed_items: int | None = None,
        failed_items: int | None = None,
    ) -> AsyncJob | None:
        """Update job progress."""
        job = await self.get(job_id)
        if not job:
            return None

        if processed_items is not None:
            job.processed_items = processed_items
        if failed_items is not None:
            job.failed_items = failed_items

        await self.db.flush()

        return job

    async def cancel(self, job_id: UUID) -> bool:
        """Cancel a job and its pending tasks."""
        job = await self.get(job_id)
        if not job:
            return False

        if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            return False

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()

        # Cancel pending tasks
        await self.db.execute(
            update(JobTask)
            .where(JobTask.job_id == job_id, JobTask.status == JobStatus.PENDING)
            .values(status=JobStatus.CANCELLED)
        )

        await self.db.flush()

        return True

    async def create_task(
        self,
        job_id: UUID,
        task_type: str,
        input_data: dict,
    ) -> JobTask:
        """Create a task for a job."""
        task = JobTask(
            job_id=job_id,
            task_type=task_type,
            input_data=input_data,
            status=JobStatus.PENDING,
        )

        self.db.add(task)
        await self.db.flush()

        return task

    async def create_tasks_batch(
        self,
        job_id: UUID,
        task_type: str,
        inputs: list[dict],
    ) -> list[JobTask]:
        """Create multiple tasks for a job."""
        tasks = [
            JobTask(
                job_id=job_id,
                task_type=task_type,
                input_data=input_data,
                status=JobStatus.PENDING,
            )
            for input_data in inputs
        ]

        self.db.add_all(tasks)
        await self.db.flush()

        return tasks

    async def update_task_status(
        self,
        task_id: UUID,
        status: JobStatus,
        output_data: dict | None = None,
        error_message: str | None = None,
    ) -> JobTask | None:
        """Update task status."""
        result = await self.db.execute(
            select(JobTask).where(JobTask.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            return None

        task.status = status
        task.attempts += 1
        task.last_attempt_at = datetime.utcnow()

        if status == JobStatus.COMPLETED:
            task.completed_at = datetime.utcnow()
        if output_data:
            task.output_data = output_data
        if error_message:
            task.error_message = error_message

        await self.db.flush()

        return task

    async def retry_failed_tasks(self, job_id: UUID) -> int:
        """Retry failed tasks in a job."""
        result = await self.db.execute(
            update(JobTask)
            .where(
                JobTask.job_id == job_id,
                JobTask.status == JobStatus.FAILED,
                JobTask.attempts < JobTask.max_attempts,
            )
            .values(status=JobStatus.PENDING, next_retry_at=datetime.utcnow())
            .returning(JobTask.id)
        )

        retried_ids = list(result.scalars().all())
        await self.db.flush()

        return len(retried_ids)
