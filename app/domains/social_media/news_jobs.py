import asyncio
import hashlib
import hmac
import html
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.domains.jobs.registry import (
    JobExecutionContext,
    PermanentJobError,
    RetryableJobError,
    job_handlers,
)
from app.domains.social_media.engagement import NewsEngagementSorter, SortedNewsCandidate
from app.domains.social_media.news_service import (
    SOCIAL_NEWS_CAPTURE_JOB,
    SOCIAL_NEWS_DISPATCH_JOB,
    SOCIAL_NEWS_REWRITE_JOB,
)
from app.integrations.ai import (
    AIRewriteClient,
    AIRewriteError,
    AIRewriteResult,
    FallbackAIRewriteClient,
    make_ai_rewrite_client,
)
from app.integrations.email import EmailService
from app.integrations.x_api import (
    XApiAuthError,
    XApiClient,
    XApiConfigurationError,
    XApiPermanentError,
    XApiRateLimitError,
    XApiTemporaryError,
    XPost,
    make_x_client,
)

logger = logging.getLogger("labby.social_news.jobs")


@job_handlers.register(SOCIAL_NEWS_CAPTURE_JOB)
def capture_social_news(context: JobExecutionContext) -> dict[str, Any]:
    with SessionLocal() as db:
        return SocialNewsJobProcessor(db).capture(context)


@job_handlers.register(SOCIAL_NEWS_REWRITE_JOB)
def rewrite_social_news_item(context: JobExecutionContext) -> dict[str, Any]:
    with SessionLocal() as db:
        return SocialNewsJobProcessor(db).rewrite(context)


@job_handlers.register(SOCIAL_NEWS_DISPATCH_JOB)
def dispatch_social_news(context: JobExecutionContext) -> dict[str, Any]:
    with SessionLocal() as db:
        return SocialNewsJobProcessor(db).dispatch(context)


class SocialNewsJobProcessor:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        sorter: NewsEngagementSorter | None = None,
        x_client_factory: Callable[[Settings], XApiClient] = make_x_client,
        ai_client_factory: Callable[[Settings], AIRewriteClient] = make_ai_rewrite_client,
        email_service: EmailService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.sorter = sorter or NewsEngagementSorter()
        self.x_client_factory = x_client_factory
        self.ai_client_factory = ai_client_factory
        self.email_service = email_service or EmailService()

    def capture(self, context: JobExecutionContext) -> dict[str, Any]:
        run_id = self._payload_id(context, "run_id")
        run = self._get_run(context.tenant_id, run_id)
        if run["status"] in {"succeeded", "cancelled"}:
            return {"run_id": run_id, "skipped": True, "status": run["status"]}

        sources = self._list_sources(context.tenant_id, str(run["segment_id"]))
        if not sources:
            self._finish_run(
                run_id=run_id,
                status="succeeded",
                candidates_count=0,
                ranked_count=0,
            )
            return {"run_id": run_id, "captured": 0, "ranked": 0}

        self._mark_run_capturing(run_id)
        try:
            capture = asyncio.run(self._capture_candidates(sources))
        except (XApiConfigurationError, XApiAuthError, XApiPermanentError) as exc:
            self._mark_run_failed(run_id, exc.__class__.__name__, str(exc))
            raise PermanentJobError(str(exc)) from exc
        except (XApiRateLimitError, XApiTemporaryError) as exc:
            self._mark_run_failed(run_id, exc.__class__.__name__, str(exc))
            raise RetryableJobError(str(exc)) from exc

        persisted = self._persist_candidates(
            tenant_id=context.tenant_id,
            run=run,
            posts_with_source=capture.posts_with_source,
        )
        sort_result = self.sorter.sort(
            [item.post for item in persisted],
            min_engagement_score=int(run.get("min_engagement_score") or 0),
            limit=max(1, self.settings.social_news_rank_limit),
            exploration_slots=1,
        )
        self._apply_rank_result(
            tenant_id=context.tenant_id,
            run_id=run_id,
            ranked=sort_result.ranked,
            discarded=sort_result.discarded,
        )
        final_status = "curation_stage1" if sort_result.ranked else "succeeded"
        self._finish_run(
            run_id=run_id,
            status=final_status,
            candidates_count=len(persisted),
            ranked_count=len(sort_result.ranked),
            x_api_cost_usd=capture.cost_usd,
            warning_message=capture.warning_message,
        )
        return {
            "run_id": run_id,
            "captured": len(persisted),
            "ranked": len(sort_result.ranked),
            "discarded": len(sort_result.discarded),
        }

    def rewrite(self, context: JobExecutionContext) -> dict[str, Any]:
        item_id = self._payload_id(context, "item_id")
        item = self._get_item_with_segment(context.tenant_id, item_id)
        if item["status"] not in {"approved_stage1", "rewritten"}:
            raise PermanentJobError("Item precisa estar aprovado no stage 1")

        result = self._rewrite_with_provider(item)
        self.db.execute(
            text(
                """
                UPDATE social_news_items
                SET status = 'rewritten',
                    rewritten_content = :content,
                    rewritten_model = :model,
                    rewritten_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :item_id
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "item_id": item_id,
                "content": result.content,
                "model": result.model,
            },
        )
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = CASE
                        WHEN status IN ('queued', 'capturing', 'curation_stage1', 'rewriting')
                        THEN 'curation_stage2'
                        ELSE status
                    END,
                    ai_cost_usd = ai_cost_usd + :ai_cost_usd,
                    estimated_cost_usd = estimated_cost_usd + :ai_cost_usd,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :run_id
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "run_id": str(item["run_id"]),
                "ai_cost_usd": result.cost_usd,
            },
        )
        self.db.commit()
        return {
            "item_id": item_id,
            "status": "rewritten",
            "model": result.model,
            "provider": result.provider,
            "provider_response_id": result.provider_response_id,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }

    def dispatch(self, context: JobExecutionContext) -> dict[str, Any]:
        run_id = self._payload_id(context, "run_id")
        run = self._get_run(context.tenant_id, run_id)
        items = self._list_approved_items(context.tenant_id, run_id)
        if not items:
            raise PermanentJobError("Nenhum item aprovado no stage 2")

        subscribers = self._list_active_subscribers(context.tenant_id, str(run["segment_id"]))
        if not subscribers:
            raise PermanentJobError("Nenhum subscriber ativo para o segmento")

        self._set_run_status(run_id, "sending")
        subject = self._subject(run, items)
        sent = 0
        failed = 0
        skipped = 0
        for subscriber in subscribers:
            dispatch = self._claim_dispatch(context.tenant_id, run, subscriber, subject)
            if not dispatch:
                skipped += 1
                continue
            unsubscribe_url = self._unsubscribe_url(subscriber)
            result = self.email_service.send_email(
                to_email=str(subscriber["email_normalized"]),
                subject=subject,
                html=self._html_digest(run, items, subscriber, unsubscribe_url),
                text=self._text_digest(run, items, unsubscribe_url),
                tags=[
                    {"name": "category", "value": "labby_social_news"},
                    {"name": "run_id", "value": run_id},
                ],
                idempotency_key=str(dispatch["idempotency_key"]),
            )
            if result.sent:
                sent += 1
                self._finish_dispatch(
                    str(dispatch["id"]),
                    "sent",
                    provider_message_id=result.provider_message_id,
                )
            else:
                failed += 1
                self._finish_dispatch(
                    str(dispatch["id"]),
                    "failed",
                    error_message=result.error,
                )

        if sent:
            self._mark_items_sent(context.tenant_id, run_id)
        self._finish_dispatch_run(run_id, sent=sent, failed=failed)
        if sent == 0 and failed > 0:
            raise RetryableJobError("Falha ao enviar todos os emails do digest")
        return {
            "run_id": run_id,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "subscribers": len(subscribers),
            "items": len(items),
        }

    async def _capture_candidates(self, sources: list[dict[str, Any]]) -> "CaptureResult":
        x_client = self.x_client_factory(self.settings)
        since = datetime.now(UTC) - timedelta(
            hours=max(1, self.settings.social_news_capture_lookback_hours)
        )
        until = datetime.now(UTC)
        candidates: list[tuple[dict[str, Any], XPost]] = []
        seen_ids: set[str] = set()
        total_cost = 0.0
        errors: list[str] = []
        planned_sources = sources[: max(1, self.settings.social_news_max_source_requests_per_run)]
        for source in planned_sources:
            try:
                page = await x_client.search_top_engagement(
                    self._query_for_source(source),
                    since=since,
                    until=until,
                    min_likes=int(source.get("min_likes") or 0),
                    min_reposts=int(source.get("min_reposts") or 0),
                    min_replies=int(source.get("min_replies") or 0),
                    min_impressions=int(source.get("min_impressions") or 0),
                    limit=max(1, self.settings.social_news_posts_per_source),
                )
            except XApiRateLimitError:
                raise
            except (XApiTemporaryError, XApiPermanentError) as exc:
                errors.append(self._source_error_message(source, exc))
                logger.warning("social_news_capture_source_failed source_id=%s", source.get("id"))
                continue

            total_cost += page.cost_usd
            for post in page.posts:
                if post.id in seen_ids or self._is_low_quality_post(post):
                    continue
                seen_ids.add(post.id)
                candidates.append((source, post))
                if len(candidates) >= max(1, self.settings.social_news_capture_limit):
                    return CaptureResult(candidates, total_cost, self._capture_warning(errors))

        return CaptureResult(candidates, total_cost, self._capture_warning(errors))

    def _persist_candidates(
        self,
        *,
        tenant_id: str,
        run: dict[str, Any],
        posts_with_source: list[tuple[dict[str, Any], XPost]],
    ) -> list["PersistedPost"]:
        persisted: list[PersistedPost] = []
        for source, post in posts_with_source:
            row = self.db.execute(
                text(
                    """
                    INSERT INTO social_news_items (
                      tenant_id,
                      run_id,
                      segment_id,
                      source_id,
                      provider,
                      external_id,
                      external_url,
                      published_at,
                      author_handle,
                      author_name,
                      author_metadata,
                      original_content,
                      media_urls,
                      metrics,
                      status
                    )
                    VALUES (
                      :tenant_id,
                      :run_id,
                      :segment_id,
                      :source_id,
                      'x',
                      :external_id,
                      :external_url,
                      :published_at,
                      :author_handle,
                      :author_name,
                      CAST(:author_metadata AS jsonb),
                      :original_content,
                      CAST(:media_urls AS jsonb),
                      CAST(:metrics AS jsonb),
                      'captured'
                    )
                    ON CONFLICT (tenant_id, provider, external_id)
                    DO UPDATE SET updated_at = NOW()
                    WHERE social_news_items.run_id = :run_id
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": str(run["id"]),
                    "segment_id": str(run["segment_id"]),
                    "source_id": str(source["id"]) if source.get("id") else None,
                    "external_id": post.id,
                    "external_url": post.url,
                    "published_at": post.created_at,
                    "author_handle": post.author.handle,
                    "author_name": post.author.name,
                    "author_metadata": json.dumps(
                        {
                            "id": post.author.id,
                            "bio": post.author.bio,
                            "verified": post.author.verified,
                            "verified_type": post.author.verified_type,
                            "followers_count": post.author.followers_count,
                            "following_count": post.author.following_count,
                            "tweet_count": post.author.tweet_count,
                            "created_at": post.author.created_at.isoformat()
                            if post.author.created_at
                            else None,
                            "profile_image_url": post.author.profile_image_url,
                            "raw": post.raw,
                        }
                    ),
                    "original_content": post.text,
                    "media_urls": json.dumps(post.media_urls),
                    "metrics": json.dumps(post.metrics()),
                },
            ).mappings().first()
            if row:
                persisted.append(PersistedPost(item_id=str(row["id"]), post=post))
        self.db.commit()
        return persisted

    def _apply_rank_result(
        self,
        *,
        tenant_id: str,
        run_id: str,
        ranked: list[SortedNewsCandidate],
        discarded: list[SortedNewsCandidate],
    ) -> None:
        for item in ranked:
            self._update_item_rank(tenant_id, run_id, item, "ranked")
        for item in discarded:
            self._update_item_rank(tenant_id, run_id, item, "discarded_rank")
        self.db.commit()

    def _update_item_rank(
        self,
        tenant_id: str,
        run_id: str,
        item: SortedNewsCandidate,
        status: str,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_items
                SET status = :status,
                    ranking_score = :ranking_score,
                    ranking_reason = :ranking_reason,
                    ranking_source = :ranking_source,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND run_id = :run_id
                  AND provider = 'x'
                  AND external_id = :external_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "status": status,
                "ranking_score": int(item.engagement_score),
                "ranking_reason": item.ranking_reason,
                "ranking_source": item.ranking_source,
                "external_id": item.post.id,
            },
        )

    def _get_run(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT r.*, s.name AS segment_name, s.disclaimer, s.min_engagement_score
                FROM social_news_runs r
                JOIN social_news_segments s
                  ON s.id = r.segment_id
                 AND s.tenant_id = r.tenant_id
                WHERE r.tenant_id = :tenant_id
                  AND r.id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().first()
        if not row:
            raise PermanentJobError("Run nao encontrada")
        return dict(row)

    def _list_sources(self, tenant_id: str, segment_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_sources
                WHERE tenant_id = :tenant_id
                  AND segment_id = :segment_id
                  AND status = 'active'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": tenant_id, "segment_id": segment_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _get_item_with_segment(self, tenant_id: str, item_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT i.*, s.name AS segment_name, s.base_knowledge, s.disclaimer
                FROM social_news_items i
                JOIN social_news_segments s
                  ON s.id = i.segment_id
                 AND s.tenant_id = i.tenant_id
                WHERE i.tenant_id = :tenant_id
                  AND i.id = :item_id
                """
            ),
            {"tenant_id": tenant_id, "item_id": item_id},
        ).mappings().first()
        if not row:
            raise PermanentJobError("Item nao encontrado")
        return dict(row)

    def _list_approved_items(self, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_items
                WHERE tenant_id = :tenant_id
                  AND run_id = :run_id
                  AND status IN ('approved_stage2', 'sent')
                ORDER BY COALESCE(ranking_score, 0) DESC, created_at ASC
                LIMIT 5
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _list_active_subscribers(self, tenant_id: str, segment_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_subscribers
                WHERE tenant_id = :tenant_id
                  AND segment_id = :segment_id
                  AND status = 'active'
                  AND consent_status = 'granted'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": tenant_id, "segment_id": segment_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _claim_dispatch(
        self,
        tenant_id: str,
        run: dict[str, Any],
        subscriber: dict[str, Any],
        subject: str,
    ) -> dict[str, Any] | None:
        idempotency_key = f"social_news_dispatch:{run['id']}:{subscriber['id']}:v1"
        row = self.db.execute(
            text(
                """
                INSERT INTO social_news_dispatches (
                  tenant_id,
                  run_id,
                  subscriber_id,
                  email_normalized,
                  subject,
                  status,
                  idempotency_key
                )
                VALUES (
                  :tenant_id,
                  :run_id,
                  :subscriber_id,
                  :email_normalized,
                  :subject,
                  'pending',
                  :idempotency_key
                )
                ON CONFLICT (run_id, subscriber_id)
                DO UPDATE SET
                  status = 'pending',
                  provider_message_id = NULL,
                  error_message = NULL,
                  updated_at = NOW()
                WHERE social_news_dispatches.status = 'failed'
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "run_id": str(run["id"]),
                "subscriber_id": str(subscriber["id"]),
                "email_normalized": str(subscriber["email_normalized"]),
                "subject": subject,
                "idempotency_key": idempotency_key,
            },
        ).mappings().first()
        self.db.commit()
        return dict(row) if row else None

    def _finish_dispatch(
        self,
        dispatch_id: str,
        status: str,
        *,
        provider_message_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_dispatches
                SET status = :status,
                    provider_message_id = :provider_message_id,
                    error_message = :error_message,
                    sent_at = CASE WHEN :status = 'sent' THEN NOW() ELSE sent_at END,
                    updated_at = NOW()
                WHERE id = :dispatch_id
                """
            ),
            {
                "dispatch_id": dispatch_id,
                "status": status,
                "provider_message_id": provider_message_id,
                "error_message": (error_message or "")[:2000] or None,
            },
        )
        self.db.commit()

    def _mark_items_sent(self, tenant_id: str, run_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_items
                SET status = 'sent',
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND run_id = :run_id
                  AND status = 'approved_stage2'
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        )
        self.db.commit()

    def _mark_run_capturing(self, run_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = 'capturing',
                    started_at = COALESCE(started_at, NOW()),
                    updated_at = NOW()
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        self.db.commit()

    def _set_run_status(self, run_id: str, status: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = :status,
                    updated_at = NOW()
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id, "status": status},
        )
        self.db.commit()

    def _finish_run(
        self,
        *,
        run_id: str,
        status: str,
        candidates_count: int,
        ranked_count: int,
        x_api_cost_usd: float = 0.0,
        warning_message: str | None = None,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = :status,
                    candidates_count = :candidates_count,
                    ranked_count = :ranked_count,
                    x_api_cost_usd = x_api_cost_usd + :x_api_cost_usd,
                    estimated_cost_usd = estimated_cost_usd + :x_api_cost_usd,
                    error_message = :warning_message,
                    finished_at = CASE
                        WHEN :status IN ('succeeded', 'failed', 'cancelled') THEN NOW()
                        ELSE finished_at
                    END,
                    updated_at = NOW()
                WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "candidates_count": candidates_count,
                "ranked_count": ranked_count,
                "x_api_cost_usd": x_api_cost_usd,
                "warning_message": warning_message,
            },
        )
        self.db.commit()

    def _finish_dispatch_run(self, run_id: str, *, sent: int, failed: int) -> None:
        final_status = "failed" if sent == 0 and failed > 0 else "succeeded"
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = :status,
                    sent_count = sent_count + :sent,
                    failed_count = failed_count + :failed,
                    finished_at = COALESCE(finished_at, NOW()),
                    updated_at = NOW()
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id, "status": final_status, "sent": sent, "failed": failed},
        )
        self.db.commit()

    def _mark_run_failed(self, run_id: str, error_code: str, error_message: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = 'failed',
                    error_code = :error_code,
                    error_message = :error_message,
                    finished_at = NOW(),
                    updated_at = NOW()
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id, "error_code": error_code, "error_message": error_message[:2000]},
        )
        self.db.commit()

    def _rewrite_with_provider(self, item: dict[str, Any]) -> AIRewriteResult:
        try:
            client = self.ai_client_factory(self.settings)
            return client.rewrite_news_item(
                segment_name=str(item.get("segment_name") or "Noticias"),
                base_knowledge=str(item.get("base_knowledge") or "") or None,
                disclaimer=str(item.get("disclaimer") or "") or None,
                original_content=str(item.get("original_content") or ""),
                external_url=str(item.get("external_url") or "") or None,
                author_handle=str(item.get("author_handle") or "") or None,
            )
        except AIRewriteError as exc:
            logger.warning(
                "social_news_rewrite_provider_failed item_id=%s provider=%s error=%s",
                item.get("id"),
                self.settings.ai_provider,
                exc,
            )
            return FallbackAIRewriteClient().rewrite_news_item(
                segment_name=str(item.get("segment_name") or "Noticias"),
                base_knowledge=str(item.get("base_knowledge") or "") or None,
                disclaimer=str(item.get("disclaimer") or "") or None,
                original_content=str(item.get("original_content") or ""),
                external_url=str(item.get("external_url") or "") or None,
                author_handle=str(item.get("author_handle") or "") or None,
            )

    def _fallback_rewrite(self, item: dict[str, Any]) -> str:
        author = html.escape(str(item.get("author_handle") or "fonte"))
        text_value = html.escape(str(item.get("original_content") or "")[:800])
        url = html.escape(str(item.get("external_url") or ""))
        disclaimer = str(item.get("disclaimer") or "").strip()
        suffix = f"\n\n{disclaimer}" if disclaimer else ""
        return f"**Atualizacao de @{author}.** {text_value}\n\nFonte: {url}{suffix}"

    def _subject(self, run: dict[str, Any], items: list[dict[str, Any]]) -> str:
        segment = run.get("segment_name") or "Noticias"
        count = len(items)
        suffix = f" - {count} destaques" if count else ""
        return f"{segment}: digest de noticias{suffix}"[:240]

    def _html_digest(
        self,
        run: dict[str, Any],
        items: list[dict[str, Any]],
        subscriber: dict[str, Any],
        unsubscribe_url: str,
    ) -> str:
        cards = "\n".join(self._html_card(item) for item in items)
        segment = html.escape(str(run.get("segment_name") or "Noticias"))
        name = html.escape(str(subscriber.get("name") or ""))
        greeting = f"Ola, {name}." if name else "Ola."
        disclaimer = html.escape(str(run.get("disclaimer") or ""))
        safe_unsubscribe = html.escape(unsubscribe_url, quote=True)
        return f"""
<!doctype html>
<html>
<body style="margin:0;background:#0b0f14;color:#e5e7eb;font-family:Arial,sans-serif;">
  <div style="max-width:680px;margin:0 auto;padding:32px 20px;">
    <p style="color:#8b949e;font-size:13px;margin:0 0 8px;">{greeting}</p>
    <h1 style="font-size:24px;line-height:1.2;margin:0 0 8px;color:#ffffff;">{segment}</h1>
    <p style="color:#a7b0ba;font-size:14px;margin:0 0 24px;">Digest curado pela Labby.</p>
    {cards}
    <p style="color:#8b949e;font-size:12px;line-height:1.6;margin-top:28px;">{disclaimer}</p>
    <p style="color:#69727d;font-size:11px;line-height:1.6;margin-top:28px;">
      Voce recebeu este email porque consentiu receber noticias deste segmento.
      <a href="{safe_unsubscribe}" style="color:#00d4aa;">Cancelar inscricao</a>
    </p>
  </div>
</body>
</html>
"""

    def _html_card(self, item: dict[str, Any]) -> str:
        content = html.escape(
            str(item.get("rewritten_content") or item.get("original_content") or "")
        )
        url = html.escape(str(item.get("external_url") or ""), quote=True)
        author = html.escape(str(item.get("author_handle") or "fonte"))
        score = html.escape(str(item.get("ranking_score") or ""))
        return f"""
    <div style="border:1px solid #24303a;background:#111820;padding:18px;margin:0 0 14px;">
      <div style="color:#00d4aa;font-size:12px;margin-bottom:10px;">
        @{author} - score {score}
      </div>
      <div style="color:#f3f4f6;font-size:15px;line-height:1.6;white-space:pre-wrap;">
        {content}
      </div>
      <a href="{url}"
         style="display:inline-block;color:#00d4aa;font-size:13px;margin-top:12px;">
        Ver fonte
      </a>
    </div>
"""

    def _text_digest(
        self,
        run: dict[str, Any],
        items: list[dict[str, Any]],
        unsubscribe_url: str,
    ) -> str:
        lines = [str(run.get("segment_name") or "Noticias"), ""]
        for item in items:
            lines.extend(
                [
                    str(item.get("rewritten_content") or item.get("original_content") or ""),
                    f"Fonte: {item.get('external_url') or ''}",
                    "",
                ]
            )
        if run.get("disclaimer"):
            lines.extend([str(run["disclaimer"]), ""])
        lines.append(f"Cancelar inscricao: {unsubscribe_url}")
        return "\n".join(lines)

    def _unsubscribe_url(self, subscriber: dict[str, Any]) -> str:
        payload = (
            f"{subscriber['tenant_id']}:{subscriber['id']}:"
            f"{str(subscriber['email_normalized']).strip().lower()}"
        )
        signature = hmac.new(
            self.settings.jwt_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        token = f"{subscriber['id']}.{signature}"
        return f"{self.settings.app_base_url.rstrip('/')}/unsubscribe/{token}"

    def _query_for_source(self, source: dict[str, Any]) -> str:
        value = str(source.get("value") or "").strip()
        if source.get("source_type") == "x_handle":
            return f"from:{value.lstrip('@')}"
        return value

    def _is_low_quality_post(self, post: XPost) -> bool:
        text = (post.text or "").casefold()
        text_without_urls = re.sub(r"https?://\S+", "", text).strip()
        meaningful_chars = re.sub(r"[^a-z0-9]", "", text_without_urls)
        if len(meaningful_chars) < 35:
            return True

        giveaway_signals = (
            "giveaway",
            "give away",
            "giving away",
            "airdrop",
            "drop addy",
            "drop address",
            "wallet address",
            "free sats",
            "lucky follower",
            "random winner",
        )
        sales_signals = ("copytrade", "copy trade", "join the discord")
        if any(signal in text for signal in giveaway_signals):
            return True
        return any(signal in text for signal in sales_signals)

    def _source_error_message(self, source: dict[str, Any], exc: Exception) -> str:
        source_id = source.get("id")
        source_type = source.get("source_type")
        source_value = source.get("value")
        return f"source {source_id} ({source_type}:{source_value}): {exc}"

    def _capture_warning(self, errors: list[str]) -> str | None:
        if not errors:
            return None
        joined = " | ".join(errors[:3])
        suffix = "" if len(errors) <= 3 else f" | +{len(errors) - 3} erros"
        return f"Captura parcial: {joined}{suffix}"[:2000]

    def _payload_id(self, context: JobExecutionContext, key: str) -> str:
        value = context.payload.get(key)
        if not value:
            raise PermanentJobError(f"Payload sem {key}")
        return str(value)


class CaptureResult:
    def __init__(
        self,
        posts_with_source: list[tuple[dict[str, Any], XPost]],
        cost_usd: float,
        warning_message: str | None,
    ) -> None:
        self.posts_with_source = posts_with_source
        self.cost_usd = cost_usd
        self.warning_message = warning_message


class PersistedPost:
    def __init__(self, *, item_id: str, post: XPost) -> None:
        self.item_id = item_id
        self.post = post
