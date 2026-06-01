import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import CurrentMembership
from app.domains.jobs.job_service import JobQueueService, JobRecord

SOCIAL_NEWS_CAPTURE_JOB = "social.news.capture"
SOCIAL_NEWS_DISPATCH_JOB = "social.news.dispatch"
SOCIAL_NEWS_REWRITE_JOB = "social.news.rewrite"
SOCIAL_INGESTION_QUEUE = "worker-social-ingestion"
SOCIAL_AI_QUEUE = "worker-ai"
SOCIAL_EMAIL_QUEUE = "worker-email"


class SocialNewsService:
    def __init__(
        self,
        db: Session,
        *,
        job_queue: JobQueueService | None = None,
    ) -> None:
        self.db = db
        self.job_queue = job_queue or JobQueueService(db)

    def list_segments(
        self,
        *,
        current: CurrentMembership,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "limit": limit,
            "offset": offset,
        }
        if status:
            where.append("status = :status")
            params["status"] = status

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_segments
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def create_segment(
        self,
        *,
        current: CurrentMembership,
        slug: str,
        name: str,
        description: str | None = None,
        base_knowledge: str | None = None,
        disclaimer: str | None = None,
        min_engagement_score: int = 0,
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        normalized_slug = _normalize_slug(slug)
        if not normalized_slug:
            raise HTTPException(status_code=422, detail="Slug invalido")

        try:
            row = self.db.execute(
                text(
                    """
                    INSERT INTO social_news_segments (
                      tenant_id,
                      slug,
                      name,
                      description,
                      base_knowledge,
                      disclaimer,
                      min_engagement_score,
                      config,
                      created_by_membership_id,
                      updated_by_membership_id
                    )
                    VALUES (
                      :tenant_id,
                      :slug,
                      :name,
                      :description,
                      :base_knowledge,
                      :disclaimer,
                      :min_engagement_score,
                      CAST(:config AS jsonb),
                      :membership_id,
                      :membership_id
                    )
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "slug": normalized_slug,
                    "name": name,
                    "description": description,
                    "base_knowledge": base_knowledge,
                    "disclaimer": disclaimer,
                    "min_engagement_score": max(0, min_engagement_score),
                    "config": json.dumps(dict(config or {})),
                    "membership_id": str(current.membership_id),
                },
            ).mappings().one()
            self.db.commit()
            return dict(row)
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Segmento ja existe") from exc

    def list_sources(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        self._get_segment(current.tenant_id, segment_id, active_only=False)
        rows = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_sources
                WHERE tenant_id = :tenant_id
                  AND segment_id = :segment_id
                ORDER BY created_at DESC
                """
            ),
            {"tenant_id": str(current.tenant_id), "segment_id": segment_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def add_source(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        source_type: str,
        value: str,
        provider: str = "x",
        min_likes: int = 0,
        min_reposts: int = 0,
        min_replies: int = 0,
        min_impressions: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        if provider != "x":
            raise HTTPException(status_code=422, detail="Provider invalido")
        if source_type not in {"x_handle", "x_keyword", "x_query"}:
            raise HTTPException(status_code=422, detail="Source type invalido")
        self._get_segment(current.tenant_id, segment_id, active_only=False)

        try:
            row = self.db.execute(
                text(
                    """
                    INSERT INTO social_news_sources (
                      tenant_id,
                      segment_id,
                      provider,
                      source_type,
                      value,
                      min_likes,
                      min_reposts,
                      min_replies,
                      min_impressions,
                      metadata_json,
                      created_by_membership_id
                    )
                    VALUES (
                      :tenant_id,
                      :segment_id,
                      :provider,
                      :source_type,
                      :value,
                      :min_likes,
                      :min_reposts,
                      :min_replies,
                      :min_impressions,
                      CAST(:metadata_json AS jsonb),
                      :membership_id
                    )
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "segment_id": segment_id,
                    "provider": provider,
                    "source_type": source_type,
                    "value": value.strip(),
                    "min_likes": max(0, min_likes),
                    "min_reposts": max(0, min_reposts),
                    "min_replies": max(0, min_replies),
                    "min_impressions": max(0, min_impressions),
                    "metadata_json": json.dumps(dict(metadata or {})),
                    "membership_id": str(current.membership_id),
                },
            ).mappings().one()
            self.db.commit()
            return dict(row)
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Fonte ja existe") from exc

    def start_run(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        idempotency_key: str | None = None,
        run_type: str = "manual",
    ) -> tuple[dict[str, Any], JobRecord]:
        self._assert_social_media_access(current)
        if run_type not in {"manual", "scheduled", "calibration"}:
            raise HTTPException(status_code=422, detail="Run type invalido")
        self._get_segment(current.tenant_id, segment_id, active_only=True)

        selected_idempotency = idempotency_key or self._manual_run_key(segment_id)
        row = self.db.execute(
            text(
                """
                INSERT INTO social_news_runs (
                  tenant_id,
                  membership_id,
                  segment_id,
                  run_type,
                  status,
                  idempotency_key,
                  window_start_at
                )
                VALUES (
                  :tenant_id,
                  :membership_id,
                  :segment_id,
                  :run_type,
                  'queued',
                  :idempotency_key,
                  :window_start_at
                )
                ON CONFLICT (tenant_id, run_type, idempotency_key)
                DO UPDATE SET updated_at = social_news_runs.updated_at
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "membership_id": str(current.membership_id),
                "segment_id": segment_id,
                "run_type": run_type,
                "idempotency_key": selected_idempotency,
                "window_start_at": datetime.now(UTC).replace(second=0, microsecond=0),
            },
        ).mappings().one()
        self.db.commit()
        run = dict(row)

        job = self.job_queue.enqueue_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            job_type=SOCIAL_NEWS_CAPTURE_JOB,
            queue_name=SOCIAL_INGESTION_QUEUE,
            idempotency_key=f"{SOCIAL_NEWS_CAPTURE_JOB}:{selected_idempotency}",
            payload={
                "run_id": str(run["id"]),
                "segment_id": segment_id,
                "provider": "x",
            },
            priority=10,
            max_attempts=3,
        )
        run = self._attach_job(run_id=str(run["id"]), tenant_id=str(current.tenant_id), job=job)
        return run, job

    def list_runs(
        self,
        *,
        current: CurrentMembership,
        segment_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "limit": limit,
            "offset": offset,
        }
        if segment_id:
            where.append("segment_id = :segment_id")
            params["segment_id"] = segment_id
        if status:
            where.append("status = :status")
            params["status"] = status

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_runs
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_run_items(
        self,
        *,
        current: CurrentMembership,
        run_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        self._get_run(current.tenant_id, run_id)
        where = ["tenant_id = :tenant_id", "run_id = :run_id"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "run_id": run_id,
            "limit": limit,
        }
        if status:
            where.append("status = :status")
            params["status"] = status

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_items
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(ranking_score, 0) DESC, created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_items(
        self,
        *,
        current: CurrentMembership,
        segment_id: str | None = None,
        run_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "limit": limit,
            "offset": offset,
        }
        if segment_id:
            self._get_segment(current.tenant_id, segment_id, active_only=False)
            where.append("segment_id = :segment_id")
            params["segment_id"] = segment_id
        if run_id:
            self._get_run(current.tenant_id, run_id)
            where.append("run_id = :run_id")
            params["run_id"] = run_id
        if status:
            where.append("status = :status")
            params["status"] = status

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_items
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(ranking_score, 0) DESC, created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def enqueue_dispatch(
        self,
        *,
        current: CurrentMembership,
        run_id: str,
        idempotency_key: str | None = None,
    ) -> JobRecord:
        self._assert_social_media_access(current)
        run = self._get_run(current.tenant_id, run_id)
        selected_idempotency = idempotency_key or f"run:{run_id}:dispatch"
        return self.job_queue.enqueue_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            job_type=SOCIAL_NEWS_DISPATCH_JOB,
            queue_name=SOCIAL_EMAIL_QUEUE,
            idempotency_key=f"{SOCIAL_NEWS_DISPATCH_JOB}:{selected_idempotency}",
            payload={
                "run_id": str(run["id"]),
                "segment_id": str(run["segment_id"]),
                "provider": "resend",
            },
            priority=5,
            max_attempts=5,
        )

    def enqueue_rewrite(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
        idempotency_key: str | None = None,
    ) -> JobRecord:
        self._assert_social_media_access(current)
        item = self._get_item(current.tenant_id, item_id)
        if item["status"] not in {"approved_stage1", "rewritten"}:
            raise HTTPException(status_code=409, detail="Item precisa estar aprovado no stage 1")
        selected_idempotency = idempotency_key or f"item:{item_id}:rewrite"
        self._mark_run_rewriting(tenant_id=str(current.tenant_id), run_id=str(item["run_id"]))
        return self._enqueue_rewrite_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            item=item,
            idempotency_key=selected_idempotency,
        )

    def approve_stage1(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], JobRecord | None]:
        self._assert_social_media_access(current)
        item = self._get_item_for_update(current.tenant_id, item_id)
        if item["status"] == "ranked":
            item = self._update_item_status(
                tenant_id=str(current.tenant_id),
                item_id=item_id,
                status="approved_stage1",
                membership_id=str(current.membership_id),
                approved_stage="stage1",
                rejection_reason=None,
            )
            self._sync_run_approval_counts(
                tenant_id=str(current.tenant_id),
                run_id=str(item["run_id"]),
            )
            self._mark_run_rewriting(
                tenant_id=str(current.tenant_id),
                run_id=str(item["run_id"]),
            )
            self.db.commit()
            selected_idempotency = idempotency_key or f"item:{item_id}:rewrite"
            job = self._enqueue_rewrite_job(
                tenant_id=str(current.tenant_id),
                membership_id=str(current.membership_id),
                item=item,
                idempotency_key=selected_idempotency,
            )
            return item, job

        self.db.commit()
        if item["status"] == "approved_stage1":
            self._mark_run_rewriting(
                tenant_id=str(current.tenant_id),
                run_id=str(item["run_id"]),
            )
            selected_idempotency = idempotency_key or f"item:{item_id}:rewrite"
            job = self._enqueue_rewrite_job(
                tenant_id=str(current.tenant_id),
                membership_id=str(current.membership_id),
                item=item,
                idempotency_key=selected_idempotency,
            )
            return item, job
        if item["status"] in {"rewritten", "approved_stage2", "sent"}:
            return item, None
        raise HTTPException(status_code=409, detail="Item nao esta pronto para stage 1")

    def reject_stage1(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        item = self._get_item_for_update(current.tenant_id, item_id)
        if item["status"] == "rejected_stage1":
            self.db.commit()
            return item
        if item["status"] != "ranked":
            self.db.commit()
            raise HTTPException(
                status_code=409,
                detail="Item nao esta pronto para rejeicao stage 1",
            )

        updated = self._update_item_status(
            tenant_id=str(current.tenant_id),
            item_id=item_id,
            status="rejected_stage1",
            membership_id=str(current.membership_id),
            approved_stage=None,
            rejection_reason=rejection_reason,
        )
        self._sync_run_approval_counts(
            tenant_id=str(current.tenant_id),
            run_id=str(updated["run_id"]),
        )
        self.db.commit()
        return updated

    def approve_stage2(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        item = self._get_item_for_update(current.tenant_id, item_id)
        if item["status"] in {"approved_stage2", "sent"}:
            self.db.commit()
            return item
        if item["status"] != "rewritten":
            self.db.commit()
            raise HTTPException(status_code=409, detail="Item precisa estar reescrito")

        updated = self._update_item_status(
            tenant_id=str(current.tenant_id),
            item_id=item_id,
            status="approved_stage2",
            membership_id=str(current.membership_id),
            approved_stage="stage2",
            rejection_reason=None,
        )
        self._sync_run_approval_counts(
            tenant_id=str(current.tenant_id),
            run_id=str(updated["run_id"]),
        )
        self.db.commit()
        return updated

    def reject_stage2(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        item = self._get_item_for_update(current.tenant_id, item_id)
        if item["status"] == "rejected_stage2":
            self.db.commit()
            return item
        if item["status"] not in {"rewritten", "approved_stage2"}:
            self.db.commit()
            raise HTTPException(
                status_code=409,
                detail="Item nao esta pronto para rejeicao stage 2",
            )

        updated = self._update_item_status(
            tenant_id=str(current.tenant_id),
            item_id=item_id,
            status="rejected_stage2",
            membership_id=str(current.membership_id),
            approved_stage=None,
            rejection_reason=rejection_reason,
            clear_stage2_approval=True,
        )
        self._sync_run_approval_counts(
            tenant_id=str(current.tenant_id),
            run_id=str(updated["run_id"]),
        )
        self.db.commit()
        return updated

    def list_subscribers(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        self._get_segment(current.tenant_id, segment_id, active_only=False)
        where = ["tenant_id = :tenant_id", "segment_id = :segment_id"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "segment_id": segment_id,
            "limit": limit,
            "offset": offset,
        }
        if status:
            where.append("status = :status")
            params["status"] = status
        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_subscribers
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def create_subscriber(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        email: str,
        name: str | None = None,
        origin: str = "manual",
        consent_source: str = "admin",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        self._get_segment(current.tenant_id, segment_id, active_only=True)
        email_normalized = _normalize_email(email)
        if not email_normalized:
            raise HTTPException(status_code=422, detail="Email invalido")

        row = self.db.execute(
            text(
                """
                INSERT INTO social_news_subscribers (
                  tenant_id,
                  segment_id,
                  email_normalized,
                  name,
                  status,
                  origin,
                  consent_status,
                  consent_source,
                  consent_given_at,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :segment_id,
                  :email_normalized,
                  :name,
                  'active',
                  :origin,
                  'granted',
                  :consent_source,
                  NOW(),
                  CAST(:metadata_json AS jsonb)
                )
                ON CONFLICT (tenant_id, segment_id, email_normalized)
                DO UPDATE SET
                  name = COALESCE(EXCLUDED.name, social_news_subscribers.name),
                  status = 'active',
                  consent_status = 'granted',
                  consent_source = EXCLUDED.consent_source,
                  consent_given_at = NOW(),
                  unsubscribed_at = NULL,
                  metadata_json = EXCLUDED.metadata_json,
                  updated_at = NOW()
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "segment_id": segment_id,
                "email_normalized": email_normalized,
                "name": name,
                "origin": origin,
                "consent_source": consent_source,
                "metadata_json": json.dumps(dict(metadata or {})),
            },
        ).mappings().one()
        subscriber = dict(row)
        token = self.build_unsubscribe_token(
            UUID(str(subscriber["tenant_id"])),
            str(subscriber["id"]),
            str(subscriber["email_normalized"]),
        )
        self.db.execute(
            text(
                """
                UPDATE social_news_subscribers
                SET unsubscribe_token_hash = :token_hash,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :subscriber_id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "subscriber_id": str(subscriber["id"]),
                "token_hash": self.hash_unsubscribe_token(token),
            },
        )
        self._record_consent_event(
            tenant_id=str(current.tenant_id),
            subscriber_id=str(subscriber["id"]),
            event_type="consent_given",
            consent_source=consent_source,
            metadata={"origin": origin, **dict(metadata or {})},
        )
        self.db.commit()
        subscriber["unsubscribe_token"] = token
        return subscriber

    def unsubscribe_by_token(
        self,
        *,
        token: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        subscriber = self.resolve_unsubscribe_token(token)
        row = self.db.execute(
            text(
                """
                UPDATE social_news_subscribers
                SET status = 'unsubscribed',
                    consent_status = 'revoked',
                    unsubscribed_at = NOW(),
                    updated_at = NOW()
                WHERE id = :subscriber_id
                RETURNING *
                """
            ),
            {"subscriber_id": str(subscriber["id"])},
        ).mappings().one()
        updated = dict(row)
        self._record_consent_event(
            tenant_id=str(updated["tenant_id"]),
            subscriber_id=str(updated["id"]),
            event_type="optout",
            consent_source="unsubscribe_link",
            ip=ip,
            user_agent=user_agent,
        )
        self.db.commit()
        return updated

    def resolve_unsubscribe_token(self, token: str) -> dict[str, Any]:
        parts = (token or "").split(".", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Token invalido")

        row = self.db.execute(
            text("SELECT * FROM social_news_subscribers WHERE id = :subscriber_id"),
            {"subscriber_id": parts[0]},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=400, detail="Token invalido")

        subscriber = dict(row)
        expected = self.build_unsubscribe_token(
            UUID(str(subscriber["tenant_id"])),
            str(subscriber["id"]),
            str(subscriber["email_normalized"]),
        )
        stored_hash = str(subscriber.get("unsubscribe_token_hash") or "")
        if not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=400, detail="Token invalido")
        if stored_hash and not hmac.compare_digest(stored_hash, self.hash_unsubscribe_token(token)):
            raise HTTPException(status_code=400, detail="Token invalido")
        return subscriber

    def build_unsubscribe_token(self, tenant_id: UUID, subscriber_id: str, email: str) -> str:
        payload = f"{tenant_id}:{subscriber_id}:{_normalize_email(email)}"
        signature = hmac.new(
            get_settings().jwt_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{subscriber_id}.{signature}"

    def hash_unsubscribe_token(self, token: str) -> str:
        return hmac.new(
            get_settings().jwt_secret.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _attach_job(self, *, run_id: str, tenant_id: str, job: JobRecord) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET job_id = :job_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :run_id
                RETURNING *
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id, "job_id": job.id},
        ).mappings().one()
        self.db.commit()
        return dict(row)

    def _get_segment(
        self,
        tenant_id: UUID,
        segment_id: str,
        *,
        active_only: bool,
    ) -> dict[str, Any]:
        where = "tenant_id = :tenant_id AND id = :segment_id"
        if active_only:
            where += " AND status = 'active'"
        row = self.db.execute(
            text(f"SELECT * FROM social_news_segments WHERE {where}"),
            {"tenant_id": str(tenant_id), "segment_id": segment_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Segmento nao encontrado")
        return dict(row)

    def _get_run(self, tenant_id: UUID, run_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_runs
                WHERE tenant_id = :tenant_id
                  AND id = :run_id
                """
            ),
            {"tenant_id": str(tenant_id), "run_id": run_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Run nao encontrada")
        return dict(row)

    def _get_item(self, tenant_id: UUID, item_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_items
                WHERE tenant_id = :tenant_id
                  AND id = :item_id
                """
            ),
            {"tenant_id": str(tenant_id), "item_id": item_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Item nao encontrado")
        return dict(row)

    def _get_item_for_update(self, tenant_id: UUID, item_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_items
                WHERE tenant_id = :tenant_id
                  AND id = :item_id
                FOR UPDATE
                """
            ),
            {"tenant_id": str(tenant_id), "item_id": item_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Item nao encontrado")
        return dict(row)

    def _update_item_status(
        self,
        *,
        tenant_id: str,
        item_id: str,
        status: str,
        membership_id: str,
        approved_stage: str | None,
        rejection_reason: str | None,
        clear_stage2_approval: bool = False,
    ) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                UPDATE social_news_items
                SET status = :status,
                    approved_stage1_by_membership_id = CASE
                        WHEN :approved_stage = 'stage1' THEN :membership_id
                        ELSE approved_stage1_by_membership_id
                    END,
                    approved_stage1_at = CASE
                        WHEN :approved_stage = 'stage1' THEN COALESCE(approved_stage1_at, NOW())
                        ELSE approved_stage1_at
                    END,
                    approved_stage2_by_membership_id = CASE
                        WHEN :approved_stage = 'stage2' THEN :membership_id
                        WHEN :clear_stage2_approval THEN NULL
                        ELSE approved_stage2_by_membership_id
                    END,
                    approved_stage2_at = CASE
                        WHEN :approved_stage = 'stage2' THEN COALESCE(approved_stage2_at, NOW())
                        WHEN :clear_stage2_approval THEN NULL
                        ELSE approved_stage2_at
                    END,
                    rejection_reason = :rejection_reason,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :item_id
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "item_id": item_id,
                "status": status,
                "membership_id": membership_id,
                "approved_stage": approved_stage,
                "clear_stage2_approval": clear_stage2_approval,
                "rejection_reason": (rejection_reason or "")[:2000] or None,
            },
        ).mappings().one()
        return dict(row)

    def _sync_run_approval_counts(self, *, tenant_id: str, run_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET approved_stage1_count = (
                        SELECT COUNT(*)
                        FROM social_news_items
                        WHERE tenant_id = :tenant_id
                          AND run_id = :run_id
                          AND status IN ('approved_stage1', 'rewritten', 'approved_stage2', 'sent')
                    ),
                    approved_stage2_count = (
                        SELECT COUNT(*)
                        FROM social_news_items
                        WHERE tenant_id = :tenant_id
                          AND run_id = :run_id
                          AND status IN ('approved_stage2', 'sent')
                    ),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        )

    def _mark_run_rewriting(self, *, tenant_id: str, run_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_news_runs
                SET status = CASE
                        WHEN status IN ('curation_stage1', 'queued', 'capturing')
                        THEN 'rewriting'
                        ELSE status
                    END,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        )
        self.db.commit()

    def _enqueue_rewrite_job(
        self,
        *,
        tenant_id: str,
        membership_id: str,
        item: Mapping[str, Any],
        idempotency_key: str,
    ) -> JobRecord:
        return self.job_queue.enqueue_job(
            tenant_id=tenant_id,
            membership_id=membership_id,
            job_type=SOCIAL_NEWS_REWRITE_JOB,
            queue_name=SOCIAL_AI_QUEUE,
            idempotency_key=f"{SOCIAL_NEWS_REWRITE_JOB}:{idempotency_key}",
            payload={
                "item_id": str(item["id"]),
                "run_id": str(item["run_id"]),
                "segment_id": str(item["segment_id"]),
            },
            priority=5,
            max_attempts=3,
        )

    def _record_consent_event(
        self,
        *,
        tenant_id: str,
        subscriber_id: str,
        event_type: str,
        consent_source: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO social_news_subscriber_consent_events (
                  tenant_id,
                  subscriber_id,
                  event_type,
                  consent_source,
                  ip,
                  user_agent,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :subscriber_id,
                  :event_type,
                  :consent_source,
                  :ip,
                  :user_agent,
                  CAST(:metadata_json AS jsonb)
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "subscriber_id": subscriber_id,
                "event_type": event_type,
                "consent_source": consent_source,
                "ip": ip,
                "user_agent": (user_agent or "")[:500] or None,
                "metadata_json": json.dumps(dict(metadata or {})),
            },
        )

    def _manual_run_key(self, segment_id: str) -> str:
        minute = datetime.now(UTC).replace(second=0, microsecond=0).isoformat()
        return f"manual:{segment_id}:{minute}"

    def _assert_social_media_access(self, current: CurrentMembership) -> None:
        if current.role == "owner":
            return
        if "social_media" not in current.modules:
            raise HTTPException(status_code=403, detail="Modulo social_media nao habilitado")


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str) -> str | None:
    normalized = (email or "").strip().lower()
    return normalized if EMAIL_RE.match(normalized) else None


def _normalize_slug(slug: str) -> str:
    value = (slug or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")
