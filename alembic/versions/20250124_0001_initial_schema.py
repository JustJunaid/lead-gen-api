"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE leadstatus AS ENUM ('new', 'enriching', 'enriched', 'verified', 'invalid', 'archived')")
    op.execute("CREATE TYPE datasource AS ENUM ('apollo', 'sales_navigator', 'linkedin_scrape', 'manual', 'csv_import', 'api')")
    op.execute("CREATE TYPE emailtype AS ENUM ('personal', 'business', 'generic')")
    op.execute("CREATE TYPE emailverificationstatus AS ENUM ('pending', 'valid', 'invalid', 'catch_all', 'unknown', 'disposable')")
    op.execute("CREATE TYPE jobtype AS ENUM ('scrape_profiles', 'enrich_emails', 'generate_content', 'import_csv', 'export_leads', 'bulk_verify')")
    op.execute("CREATE TYPE jobstatus AS ENUM ('pending', 'queued', 'running', 'paused', 'completed', 'failed', 'cancelled')")

    # Users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('hashed_password', sa.String(255)),
        sa.Column('full_name', sa.String(255)),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('is_superuser', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # API Keys table
    op.create_table(
        'api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('key_hash', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('key_prefix', sa.String(10), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('scopes', postgresql.JSONB(), default=['read', 'write']),
        sa.Column('rate_limit_per_minute', sa.Integer(), default=60),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True)),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # User Settings table
    op.create_table(
        'user_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('openai_api_key_encrypted', sa.LargeBinary()),
        sa.Column('anthropic_api_key_encrypted', sa.LargeBinary()),
        sa.Column('google_ai_api_key_encrypted', sa.LargeBinary()),
        sa.Column('default_ai_provider', sa.String(50), default='openai'),
        sa.Column('default_ai_model', sa.String(100), default='gpt-4o-mini'),
        sa.Column('scraping_rate_limit_per_hour', sa.Integer(), default=1000),
        sa.Column('ai_requests_per_day', sa.Integer(), default=500),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Companies table
    op.create_table(
        'companies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(500), nullable=False, index=True),
        sa.Column('domain', sa.String(255), unique=True, index=True),
        sa.Column('linkedin_url', sa.String(500), index=True),
        sa.Column('website', sa.String(500)),
        sa.Column('industry', sa.String(255)),
        sa.Column('employee_count_range', sa.String(50)),
        sa.Column('revenue_range', sa.String(100)),
        sa.Column('description', sa.Text()),
        sa.Column('logo_url', sa.String(500)),
        sa.Column('headquarters_city', sa.String(255)),
        sa.Column('headquarters_state', sa.String(100)),
        sa.Column('headquarters_country', sa.String(100)),
        sa.Column('detected_email_pattern', sa.String(50)),
        sa.Column('email_pattern_confidence', sa.Numeric(3, 2)),
        sa.Column('source', sa.String(50)),
        sa.Column('source_id', sa.String(255)),
        sa.Column('last_enriched_at', sa.DateTime(timezone=True)),
        sa.Column('data_quality_score', sa.Numeric(3, 2)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Leads table
    op.create_table(
        'leads',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), index=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='SET NULL'), index=True),
        sa.Column('first_name', sa.String(255)),
        sa.Column('last_name', sa.String(255)),
        sa.Column('full_name', sa.String(500), index=True),
        sa.Column('job_title', sa.String(500)),
        sa.Column('job_title_normalized', sa.String(255)),
        sa.Column('seniority_level', sa.String(50)),
        sa.Column('department', sa.String(100)),
        sa.Column('linkedin_url', sa.String(500), unique=True, index=True),
        sa.Column('linkedin_username', sa.String(255)),
        sa.Column('personal_city', sa.String(255)),
        sa.Column('personal_state', sa.String(100)),
        sa.Column('personal_country', sa.String(100)),
        sa.Column('status', postgresql.ENUM('new', 'enriching', 'enriched', 'verified', 'invalid', 'archived', name='leadstatus', create_type=False), default='new', index=True),
        sa.Column('data_quality_score', sa.Numeric(3, 2)),
        sa.Column('source', postgresql.ENUM('apollo', 'sales_navigator', 'linkedin_scrape', 'manual', 'csv_import', 'api', name='datasource', create_type=False), nullable=False),
        sa.Column('source_id', sa.String(255)),
        sa.Column('source_file', sa.String(500)),
        sa.Column('dedup_key', sa.String(255), index=True),
        sa.Column('merged_into_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id', ondelete='SET NULL')),
        sa.Column('last_enriched_at', sa.DateTime(timezone=True)),
        sa.Column('last_scraped_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Emails table
    op.create_table(
        'emails',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('email', sa.String(255), nullable=False, index=True),
        sa.Column('email_type', postgresql.ENUM('personal', 'business', 'generic', name='emailtype', create_type=False)),
        sa.Column('is_primary', sa.Boolean(), default=False),
        sa.Column('verification_status', postgresql.ENUM('pending', 'valid', 'invalid', 'catch_all', 'unknown', 'disposable', name='emailverificationstatus', create_type=False), default='pending', index=True),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('verification_provider', sa.String(50)),
        sa.Column('source', sa.String(50)),
        sa.Column('pattern_used', sa.String(50)),
        sa.Column('confidence_score', sa.Numeric(3, 2)),
        sa.Column('last_seen_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('lead_id', 'email', name='uq_lead_email'),
    )

    # LinkedIn Profiles table
    op.create_table(
        'linkedin_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('headline', sa.String(500)),
        sa.Column('summary', sa.Text()),
        sa.Column('location', sa.String(255)),
        sa.Column('profile_picture_url', sa.String(500)),
        sa.Column('banner_url', sa.String(500)),
        sa.Column('connections_count', sa.Integer()),
        sa.Column('followers_count', sa.Integer()),
        sa.Column('experiences', postgresql.JSONB()),
        sa.Column('education', postgresql.JSONB()),
        sa.Column('skills', postgresql.JSONB()),
        sa.Column('certifications', postgresql.JSONB()),
        sa.Column('languages', postgresql.JSONB()),
        sa.Column('recent_posts', postgresql.JSONB()),
        sa.Column('recent_comments', postgresql.JSONB()),
        sa.Column('raw_response', postgresql.JSONB()),
        sa.Column('scraper_provider', sa.String(50)),
        sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Async Jobs table
    op.create_table(
        'async_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('job_type', postgresql.ENUM('scrape_profiles', 'enrich_emails', 'generate_content', 'import_csv', 'export_leads', 'bulk_verify', name='jobtype', create_type=False), nullable=False, index=True),
        sa.Column('status', postgresql.ENUM('pending', 'queued', 'running', 'paused', 'completed', 'failed', 'cancelled', name='jobstatus', create_type=False), default='pending', index=True),
        sa.Column('priority', sa.Integer(), default=5),
        sa.Column('total_items', sa.Integer(), default=0),
        sa.Column('processed_items', sa.Integer(), default=0),
        sa.Column('failed_items', sa.Integer(), default=0),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('result', postgresql.JSONB()),
        sa.Column('error_message', sa.Text()),
        sa.Column('error_details', postgresql.JSONB()),
        sa.Column('scheduled_at', sa.DateTime(timezone=True)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('estimated_completion', sa.DateTime(timezone=True)),
        sa.Column('celery_task_id', sa.String(255), index=True),
        sa.Column('webhook_url', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Job Tasks table
    op.create_table(
        'job_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('async_jobs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'queued', 'running', 'paused', 'completed', 'failed', 'cancelled', name='jobstatus', create_type=False), default='pending', index=True),
        sa.Column('input_data', postgresql.JSONB(), nullable=False),
        sa.Column('output_data', postgresql.JSONB()),
        sa.Column('error_message', sa.Text()),
        sa.Column('attempts', sa.Integer(), default=0),
        sa.Column('max_attempts', sa.Integer(), default=3),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), index=True),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('job_tasks')
    op.drop_table('async_jobs')
    op.drop_table('linkedin_profiles')
    op.drop_table('emails')
    op.drop_table('leads')
    op.drop_table('companies')
    op.drop_table('user_settings')
    op.drop_table('api_keys')
    op.drop_table('users')

    # Drop enum types
    op.execute("DROP TYPE jobstatus")
    op.execute("DROP TYPE jobtype")
    op.execute("DROP TYPE emailverificationstatus")
    op.execute("DROP TYPE emailtype")
    op.execute("DROP TYPE datasource")
    op.execute("DROP TYPE leadstatus")
