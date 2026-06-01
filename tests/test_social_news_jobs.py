from datetime import datetime

from app.domains.jobs.registry import job_handlers
from app.domains.social_media import news_jobs  # noqa: F401
from app.domains.social_media.engagement import NewsEngagementSorter
from app.domains.social_media.news_service import (
    SOCIAL_NEWS_CAPTURE_JOB,
    SOCIAL_NEWS_DISPATCH_JOB,
    SOCIAL_NEWS_REWRITE_JOB,
)
from app.integrations.ai import OpenAIResponsesRewriteClient
from app.integrations.email import EmailService
from app.integrations.x_api import TwitterApiIoAdapter, XAuthor, XPost


def test_social_news_job_handlers_are_registered() -> None:
    assert job_handlers.get(SOCIAL_NEWS_CAPTURE_JOB) is not None
    assert job_handlers.get(SOCIAL_NEWS_REWRITE_JOB) is not None
    assert job_handlers.get(SOCIAL_NEWS_DISPATCH_JOB) is not None


def test_engagement_sorter_ranks_by_score_and_threshold() -> None:
    sorter = NewsEngagementSorter()
    author = XAuthor(id="u1", handle="labby")
    low = XPost(id="1", url="", text="post low", author=author, like_count=1)
    high = XPost(id="2", url="", text="post high", author=author, like_count=30, reply_count=5)

    result = sorter.sort([low, high], min_engagement_score=10, limit=2, exploration_slots=0)

    assert [item.post.id for item in result.ranked] == ["2"]
    assert [item.post.id for item in result.discarded] == ["1"]


def test_twitterapi_io_adapter_parses_posts() -> None:
    adapter = TwitterApiIoAdapter(api_key="key", timeout_seconds=1)

    post = adapter._parse_post(
        {
            "id": "123",
            "text": "Labby news post with enough content",
            "createdAt": "2026-06-01T12:00:00Z",
            "likeCount": 10,
            "retweetCount": 2,
            "replyCount": 1,
            "quoteCount": 3,
            "viewCount": 1000,
            "author": {
                "id": "u1",
                "userName": "labby",
                "name": "Labby",
                "followers": 50,
            },
        }
    )

    assert post.id == "123"
    assert post.url == "https://x.com/labby/status/123"
    assert post.created_at == datetime(2026, 6, 1, 12, 0)
    assert post.metrics() == {
        "likes": 10,
        "retweets": 2,
        "replies": 1,
        "quotes": 3,
        "impressions": 1000,
    }


def test_generic_email_send_requires_resend_key(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("LABBY_RESEND_API_KEY", raising=False)
    result = EmailService().send_email(
        to_email="user@example.com",
        subject="Digest",
        html="<p>Digest</p>",
    )

    assert result.sent is False
    assert result.error == "RESEND_API_KEY nao configurada"
    get_settings.cache_clear()


def test_openai_responses_rewrite_client_parses_output_text(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "id": "resp_123",
                "model": "gpt-4o-mini",
                "output_text": "Texto final do digest.",
                "usage": {"input_tokens": 20, "output_tokens": 8},
            }

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr("app.integrations.ai.httpx.post", fake_post)
    client = OpenAIResponsesRewriteClient(
        api_key="key",
        model="gpt-4o-mini",
        timeout_seconds=1,
        input_cost_per_million_tokens=1.0,
        output_cost_per_million_tokens=2.0,
    )

    result = client.rewrite_news_item(
        segment_name="Crypto",
        base_knowledge="Contexto",
        disclaimer="Nao e recomendacao financeira.",
        original_content="Post original com informacao importante.",
        external_url="https://x.com/labby/status/1",
        author_handle="labby",
    )

    assert result.content == "Texto final do digest."
    assert result.provider == "openai"
    assert result.provider_response_id == "resp_123"
    assert result.input_tokens == 20
    assert result.output_tokens == 8
    assert result.cost_usd == 0.000036
    assert calls[0][1]["json"]["model"] == "gpt-4o-mini"
    assert calls[0][1]["json"]["max_output_tokens"] == 700
