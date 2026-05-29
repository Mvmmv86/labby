from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "labby",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    timezone=settings.timezone,
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60 * 15,
    task_soft_time_limit=60 * 10,
    worker_prefetch_multiplier=1,
    beat_schedule={},
)

celery_app.autodiscover_tasks(["app.jobs"])
