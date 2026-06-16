from datetime import UTC, datetime, timedelta

from app.domains.social_media.onboarding_service import (
    _public_reference_job_can_attempt,
    _summarize_phyllo_contents,
)


def test_phyllo_engagement_rate_by_followers_is_average_per_content() -> None:
    summary = _summarize_phyllo_contents(
        [
            {
                "id": "one",
                "engagement": {
                    "like_count": 120,
                    "comment_count": 12,
                    "share_count": 8,
                    "save_count": 20,
                    "reach_organic_count": 3400,
                },
            },
            {
                "id": "two",
                "engagement": {
                    "like_count": 80,
                    "comment_count": 4,
                    "share_count": 1,
                    "save_count": 3,
                    "reach_organic_count": 900,
                },
            },
        ],
        followers_count=4200,
    )

    assert summary["content_metrics"]["interactions"] == 248
    assert summary["content_metrics"]["engagement_rate_by_followers"] == 2.95
    assert summary["content_metrics"]["engagement_rate_by_reach"] == 5.77


def test_public_reference_job_allows_pending_but_keeps_failed_cooldown() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)

    assert _public_reference_job_can_attempt(
        {"sync_status": "pending", "next_sync_after": future},
        circuit_breaker_failures=3,
    )
    assert not _public_reference_job_can_attempt(
        {
            "sync_status": "failed",
            "next_sync_after": future,
            "failure_count": 1,
        },
        circuit_breaker_failures=3,
    )
    assert not _public_reference_job_can_attempt(
        {
            "sync_status": "partially_synced",
            "next_sync_after": future,
            "failure_count": 1,
        },
        circuit_breaker_failures=3,
    )
