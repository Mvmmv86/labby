from app.domains.social_media.onboarding_service import _summarize_phyllo_contents


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
