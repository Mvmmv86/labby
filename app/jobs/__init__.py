"""Celery jobs package."""

from app.jobs.smoke import ping

__all__ = ["ping"]
