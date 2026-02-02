"""Celery application configuration."""

from celery import Celery
from kombu import Queue, Exchange

from leadgen.config import settings

celery_app = Celery(
    "leadgen",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "leadgen.workers.tasks.scraping",
        "leadgen.workers.tasks.enrichment",
        "leadgen.workers.tasks.ai",
        "leadgen.workers.tasks.imports",
    ],
)

# Task queues
celery_app.conf.task_queues = [
    Queue("scraping.high", Exchange("scraping"), routing_key="scraping.high"),
    Queue("scraping.low", Exchange("scraping"), routing_key="scraping.low"),
    Queue("enrichment", Exchange("enrichment"), routing_key="enrichment"),
    Queue("ai.fast", Exchange("ai"), routing_key="ai.fast"),
    Queue("ai.slow", Exchange("ai"), routing_key="ai.slow"),
    Queue("import", Exchange("import"), routing_key="import"),
    Queue("default", Exchange("default"), routing_key="default"),
]

# Task routing
celery_app.conf.task_routes = {
    "leadgen.workers.tasks.scraping.scrape_single_profile": {"queue": "scraping.high"},
    "leadgen.workers.tasks.scraping.scrape_batch_profiles": {"queue": "scraping.low"},
    "leadgen.workers.tasks.enrichment.*": {"queue": "enrichment"},
    "leadgen.workers.tasks.ai.generate_cold_email": {"queue": "ai.fast"},
    "leadgen.workers.tasks.ai.generate_bulk_emails": {"queue": "ai.slow"},
    "leadgen.workers.tasks.imports.*": {"queue": "import"},
}

# Rate limiting per task
celery_app.conf.task_annotations = {
    "leadgen.workers.tasks.scraping.*": {
        "rate_limit": f"{settings.scraping_default_rate_limit}/m",
        "max_retries": settings.scraping_retry_attempts,
        "default_retry_delay": 60,
    },
    "leadgen.workers.tasks.ai.*": {
        "rate_limit": f"{settings.ai_requests_per_minute}/m",
        "max_retries": 2,
    },
}

# Concurrency settings
celery_app.conf.worker_concurrency = 4
celery_app.conf.worker_prefetch_multiplier = 2

# Task serialization
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

# Result expiration
celery_app.conf.result_expires = 86400  # 24 hours

# Visibility timeout for long-running tasks
celery_app.conf.broker_transport_options = {
    "visibility_timeout": 3600,  # 1 hour
}

# Timezone
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
