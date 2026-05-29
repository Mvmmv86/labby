from app.core.celery_app import celery_app
from app.jobs.smoke import ping


def test_celery_ping_task_runs_in_eager_mode() -> None:
    previous_always_eager = celery_app.conf.task_always_eager
    previous_eager_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        result = ping.delay()
        assert result.get(timeout=1) == "pong"
    finally:
        celery_app.conf.task_always_eager = previous_always_eager
        celery_app.conf.task_eager_propagates = previous_eager_propagates
