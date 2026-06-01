import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

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
DEFAULT_SCHEDULE_TIMEZONE = "America/Sao_Paulo"
FIXED_EXPLORATORY_HOURS = (9, 14, 21)
SOCIAL_NEWS_SEEDS: dict[str, dict[str, Any]] = {
    "crypto_v1": {
        "slug": "crypto",
        "name": "Criptomoeda",
        "idioma": "pt",
        "description": "Noticias sobre Bitcoin, Ethereum, altcoins, regulacao e mercado cripto",
        "seed_origem": "crypto_v1",
        "disclaimer": (
            "Este conteudo e informativo e nao constitui recomendacao financeira. "
            "Faca sua propria pesquisa."
        ),
        "base_knowledge": None,
        "vocabulario": [
            "BTC",
            "ETH",
            "altcoin",
            "DeFi",
            "ETF",
            "Halving",
            "FOMC",
            "SEC",
            "CVM",
            "stablecoin",
        ],
        "tipos_evento": [
            "etf_approval",
            "hack_exchange",
            "regulacao_sec_cvm",
            "halving",
            "listagem_grande",
            "lancamento_protocolo",
        ],
        "handles": [],
        "keywords": ["bitcoin", "BTC", "ethereum", "ETH", "ETF", "SEC", "halving"],
        "min_engagement_score": 0,
    },
}


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
        active: bool | None = None,
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
        if status == "capturando":
            where.append("status IN ('queued', 'capturing')")
        elif status:
            where.append("status = :status")
            params["status"] = status
        if active is not None:
            where.append("status = :active_status")
            params["active_status"] = "active" if active else "inactive"

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_segments
                WHERE {' AND '.join(where)}
                ORDER BY name ASC, created_at DESC
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

    def create_segment_from_seed(
        self,
        *,
        current: CurrentMembership,
        seed_origem: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        seed = SOCIAL_NEWS_SEEDS.get(seed_origem)
        if not seed:
            available = ", ".join(sorted(SOCIAL_NEWS_SEEDS))
            raise HTTPException(
                status_code=404,
                detail=f"seed_origem '{seed_origem}' nao registrado. Disponiveis: {available}",
            )

        config = {
            "idioma": seed.get("idioma", "pt"),
            "seed_origem": seed_origem,
            "vocabulario": seed.get("vocabulario") or [],
            "tipos_evento": seed.get("tipos_evento") or [],
        }
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
                    "slug": str(seed["slug"]),
                    "name": str(seed["name"]),
                    "description": seed.get("description"),
                    "base_knowledge": seed.get("base_knowledge"),
                    "disclaimer": seed.get("disclaimer"),
                    "min_engagement_score": int(seed.get("min_engagement_score") or 0),
                    "config": json.dumps(config),
                    "membership_id": str(current.membership_id),
                },
            ).mappings().one()
            segment = dict(row)

            for handle in seed.get("handles") or []:
                value = str(handle).strip()
                if value and not _is_placeholder(value):
                    self._insert_source(
                        current=current,
                        segment_id=str(segment["id"]),
                        source_type="x_handle",
                        value=value,
                        metadata={"origem": "seed"},
                    )
            for keyword in seed.get("keywords") or []:
                value = str(keyword).strip()
                if value and not _is_placeholder(value):
                    self._insert_source(
                        current=current,
                        segment_id=str(segment["id"]),
                        source_type="x_keyword",
                        value=value,
                        metadata={"origem": "seed"},
                    )

            self.db.commit()
            return segment
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Segmento ja existe") from exc

    def get_segment(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        return self._get_segment(current.tenant_id, segment_id, active_only=False)

    def update_segment(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        segment = self._get_segment(current.tenant_id, segment_id, active_only=False)
        config = dict(segment.get("config") or {})
        if "config" in patch and isinstance(patch["config"], Mapping):
            config.update(dict(patch["config"]))
        for key in ("idioma", "tipos_evento", "vocabulario"):
            if key in patch:
                config[key] = patch[key]

        status = patch.get("status")
        if "ativo" in patch and patch["ativo"] is not None:
            status = "active" if patch["ativo"] else "inactive"
        fields = {
            "name": patch.get("name") or patch.get("nome"),
            "description": patch.get("description")
            if "description" in patch
            else patch.get("descricao"),
            "base_knowledge": patch.get("base_knowledge")
            if "base_knowledge" in patch
            else patch.get("base_conhecimento"),
            "disclaimer": patch.get("disclaimer"),
            "min_engagement_score": patch.get("min_engagement_score"),
            "status": status,
            "config": json.dumps(config),
            "updated_by_membership_id": str(current.membership_id),
        }
        set_parts = [
            f"{key} = :{key}"
            for key, value in fields.items()
            if value is not None or key == "config"
        ]
        set_parts.append("updated_at = NOW()")
        row = self.db.execute(
            text(
                f"""
                UPDATE social_news_segments
                SET {', '.join(set_parts)}
                WHERE tenant_id = :tenant_id
                  AND id = :segment_id
                RETURNING *
                """
            ),
            {
                **{
                    key: value
                    for key, value in fields.items()
                    if value is not None or key == "config"
                },
                "tenant_id": str(current.tenant_id),
                "segment_id": segment_id,
            },
        ).mappings().first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Segmento nao encontrado")
        self.db.commit()
        return dict(row)

    def delete_segment(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
    ) -> None:
        self._assert_social_media_access(current)
        row = self.db.execute(
            text(
                """
                UPDATE social_news_segments
                SET status = 'inactive',
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :segment_id
                  AND status = 'active'
                RETURNING id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "segment_id": segment_id,
                "membership_id": str(current.membership_id),
            },
        ).first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Segmento nao encontrado")
        self.db.commit()

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
                  AND status <> 'archived'
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
        min_likes: int = 100,
        min_reposts: int = 50,
        min_replies: int = 10,
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
            row = self._insert_source(
                current=current,
                segment_id=segment_id,
                source_type=source_type,
                value=value,
                provider=provider,
                min_likes=min_likes,
                min_reposts=min_reposts,
                min_replies=min_replies,
                min_impressions=min_impressions,
                metadata={"origem": "user", **dict(metadata or {})},
            )
            self.db.commit()
            return dict(row)
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Fonte ja existe") from exc

    def delete_source(
        self,
        *,
        current: CurrentMembership,
        source_id: str,
    ) -> None:
        self._assert_social_media_access(current)
        row = self.db.execute(
            text(
                """
                UPDATE social_news_sources
                SET status = 'archived',
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :source_id
                  AND status <> 'archived'
                RETURNING id
                """
            ),
            {"tenant_id": str(current.tenant_id), "source_id": source_id},
        ).first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Fonte nao encontrada")
        self.db.commit()

    def get_curator(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        self._get_segment(current.tenant_id, segment_id, active_only=False)
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_curators
                WHERE tenant_id = :tenant_id
                  AND segment_id = :segment_id
                  AND status <> 'archived'
                """
            ),
            {"tenant_id": str(current.tenant_id), "segment_id": segment_id},
        ).mappings().first()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="Curator nao configurado para este segmento",
            )
        return dict(row)

    def upsert_curator(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        name: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.4,
        max_tokens: int = 600,
        system_prompt: str | None = None,
        base_knowledge: str | None = None,
        active: bool | None = None,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        self._get_segment(current.tenant_id, segment_id, active_only=False)
        status_value = "active" if active is not False else "inactive"
        row = self.db.execute(
            text(
                """
                INSERT INTO social_news_curators (
                  tenant_id,
                  segment_id,
                  name,
                  model,
                  temperature,
                  max_tokens,
                  system_prompt,
                  base_knowledge,
                  status,
                  updated_by_membership_id
                )
                VALUES (
                  :tenant_id,
                  :segment_id,
                  :name,
                  :model,
                  :temperature,
                  :max_tokens,
                  :system_prompt,
                  :base_knowledge,
                  :status,
                  :membership_id
                )
                ON CONFLICT (tenant_id, segment_id)
                DO UPDATE SET
                  name = EXCLUDED.name,
                  model = EXCLUDED.model,
                  temperature = EXCLUDED.temperature,
                  max_tokens = EXCLUDED.max_tokens,
                  system_prompt = EXCLUDED.system_prompt,
                  base_knowledge = EXCLUDED.base_knowledge,
                  status = EXCLUDED.status,
                  updated_by_membership_id = EXCLUDED.updated_by_membership_id,
                  updated_at = NOW()
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "segment_id": segment_id,
                "name": name,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "system_prompt": system_prompt,
                "base_knowledge": base_knowledge,
                "status": status_value,
                "membership_id": str(current.membership_id),
            },
        ).mappings().one()
        self.db.commit()
        return dict(row)

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
        run_type: str | None = None,
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
        if run_type:
            where.append("run_type = :run_type")
            params["run_type"] = run_type
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

    def get_run(
        self,
        *,
        current: CurrentMembership,
        run_id: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        return self._get_run(current.tenant_id, run_id)

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
        job = self._enqueue_rewrite_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            item=item,
            idempotency_key=selected_idempotency,
            commit=False,
        )
        self.db.commit()
        return job

    def approve_stage1(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
        idempotency_key: str | None = None,
        rewrite_on_approve: bool = True,
    ) -> tuple[dict[str, Any], JobRecord | None]:
        self._assert_social_media_access(current)
        item = self._get_item_for_update(current.tenant_id, item_id)
        job = None
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
            if rewrite_on_approve:
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
                    commit=False,
                )
            self.db.commit()
            return item, job

        if item["status"] == "approved_stage1":
            if rewrite_on_approve:
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
                    commit=False,
                )
            self.db.commit()
            return item, job
        if item["status"] in {"rewritten", "approved_stage2", "sent"}:
            self.db.commit()
            return item, None
        self.db.commit()
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
        segment_id: str | None = None,
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

    def get_subscriber(
        self,
        *,
        current: CurrentMembership,
        subscriber_id: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_subscribers
                WHERE tenant_id = :tenant_id
                  AND id = :subscriber_id
                """
            ),
            {"tenant_id": str(current.tenant_id), "subscriber_id": subscriber_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Subscriber nao encontrado")
        return dict(row)

    def update_subscriber(
        self,
        *,
        current: CurrentMembership,
        subscriber_id: str,
        patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        fields: dict[str, Any] = {}
        if "nome" in patch and patch["nome"] is not None:
            fields["name"] = patch["nome"]
        if "status" in patch and patch["status"] is not None:
            fields["status"] = patch["status"]
            if patch["status"] == "active":
                fields["consent_status"] = "granted"
                fields["unsubscribed_at"] = None
            elif patch["status"] in {"unsubscribed", "removed"}:
                fields["consent_status"] = "revoked"
                fields["unsubscribed_at"] = datetime.now(UTC)
        if "metadata" in patch and patch["metadata"] is not None:
            fields["metadata_json"] = json.dumps(dict(patch["metadata"] or {}))
        if not fields:
            return self.get_subscriber(current=current, subscriber_id=subscriber_id)

        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        row = self.db.execute(
            text(
                f"""
                UPDATE social_news_subscribers
                SET {set_clause},
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :subscriber_id
                RETURNING *
                """
            ),
            {
                **fields,
                "tenant_id": str(current.tenant_id),
                "subscriber_id": subscriber_id,
            },
        ).mappings().first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Subscriber nao encontrado")
        updated = dict(row)
        if "status" in patch:
            self._record_consent_event(
                tenant_id=str(current.tenant_id),
                subscriber_id=str(updated["id"]),
                event_type="reactivate" if patch["status"] == "active" else "admin_update",
                consent_source="admin",
                metadata={"status": patch["status"]},
            )
        self.db.commit()
        return updated

    def delete_subscriber(
        self,
        *,
        current: CurrentMembership,
        subscriber_id: str,
    ) -> None:
        self.update_subscriber(
            current=current,
            subscriber_id=subscriber_id,
            patch={"status": "removed"},
        )

    def get_item(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        return self._get_item(current.tenant_id, item_id)

    def dispatch_preview(
        self,
        *,
        current: CurrentMembership,
        run_id: str,
    ) -> dict[str, int | str]:
        self._assert_social_media_access(current)
        run = self._get_run(current.tenant_id, run_id)
        counts = self.db.execute(
            text(
                """
                SELECT
                  (
                    SELECT COUNT(*)
                    FROM social_news_items
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND status IN ('approved_stage2', 'sent')
                  ) AS items,
                  (
                    SELECT COUNT(*)
                    FROM social_news_subscribers
                    WHERE tenant_id = :tenant_id
                      AND segment_id = :segment_id
                      AND status = 'active'
                      AND consent_status = 'granted'
                  ) AS subscribers
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "run_id": run_id,
                "segment_id": str(run["segment_id"]),
            },
        ).mappings().one()
        return {
            "run_id": run_id,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "subscribers": int(counts["subscribers"] or 0),
            "items": int(counts["items"] or 0),
        }

    def list_dispatches(
        self,
        *,
        current: CurrentMembership,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "limit": limit,
        }
        if run_id:
            self._get_run(current.tenant_id, run_id)
            where.append("run_id = :run_id")
            params["run_id"] = run_id

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_dispatches
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_schedules(
        self,
        *,
        current: CurrentMembership,
        segment_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        self._assert_social_media_access(current)
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(current.tenant_id)}
        if segment_id:
            self._get_segment(current.tenant_id, segment_id, active_only=False)
            where.append("segment_id = :segment_id")
            params["segment_id"] = segment_id
        if active_only:
            where.append("status = 'active'")

        rows = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_schedules
                WHERE {' AND '.join(where)}
                ORDER BY
                  CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                  COALESCE(day_of_week, 99),
                  scheduled_hour,
                  scheduled_minute,
                  confidence_score DESC
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def recalibrate_schedules(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self._assert_social_media_access(current)
        self._get_segment(current.tenant_id, segment_id, active_only=True)
        run = self._create_calibration_run(current=current, segment_id=segment_id)
        buckets = self._schedule_buckets(segment_id=segment_id, tenant_id=str(current.tenant_id))

        for bucket in buckets[:3]:
            self._upsert_schedule(
                current=current,
                segment_id=segment_id,
                day_of_week=bucket["day_of_week"],
                window_start_hour=bucket["window_start_hour"],
                window_end_hour=min(int(bucket["window_start_hour"]) + 4, 24),
                scheduled_hour=bucket["window_start_hour"],
                scheduled_minute=0,
                confidence_score=bucket["confidence_score"],
                samples_count=bucket["samples_count"],
                average_score=bucket["average_score"],
                discovered_by="ia",
                origin_run_id=str(run["id"]),
                name=_schedule_name(bucket["day_of_week"], bucket["window_start_hour"]),
            )

        for hour in FIXED_EXPLORATORY_HOURS:
            self._upsert_schedule(
                current=current,
                segment_id=segment_id,
                day_of_week=None,
                window_start_hour=hour,
                window_end_hour=min(hour + 4, 24),
                scheduled_hour=hour,
                scheduled_minute=0,
                confidence_score=45,
                samples_count=0,
                average_score=None,
                discovered_by="exploratorio_fixo",
                origin_run_id=str(run["id"]),
                name=f"Exploratorio diario {hour:02d}:00",
            )

        self.db.commit()
        return run, self.list_schedules(current=current, segment_id=segment_id)

    def update_schedule(
        self,
        *,
        current: CurrentMembership,
        schedule_id: str,
        patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._assert_social_media_access(current)
        schedule = self._get_schedule(current.tenant_id, schedule_id)
        fields: dict[str, Any] = {}
        if "nome" in patch and patch["nome"] is not None:
            fields["name"] = patch["nome"]
        if "scheduled_hour" in patch and patch["scheduled_hour"] is not None:
            fields["scheduled_hour"] = patch["scheduled_hour"]
        if "scheduled_minute" in patch and patch["scheduled_minute"] is not None:
            fields["scheduled_minute"] = patch["scheduled_minute"]
        if "confidence_score" in patch and patch["confidence_score"] is not None:
            fields["confidence_score"] = patch["confidence_score"]
        if "ativo" in patch and patch["ativo"] is not None:
            fields["status"] = "active" if patch["ativo"] else "inactive"
        if not fields:
            return schedule

        merged = {**schedule, **fields}
        fields["next_run_at"] = _next_schedule_run_at(merged)
        fields["updated_by_membership_id"] = str(current.membership_id)
        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        row = self.db.execute(
            text(
                f"""
                UPDATE social_news_schedules
                SET {set_clause},
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :schedule_id
                RETURNING *
                """
            ),
            {
                **fields,
                "tenant_id": str(current.tenant_id),
                "schedule_id": schedule_id,
            },
        ).mappings().first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Schedule nao encontrado")
        self.db.commit()
        return dict(row)

    def delete_schedule(
        self,
        *,
        current: CurrentMembership,
        schedule_id: str,
    ) -> None:
        self._assert_social_media_access(current)
        row = self.db.execute(
            text(
                """
                UPDATE social_news_schedules
                SET status = 'inactive',
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :schedule_id
                  AND status = 'active'
                RETURNING id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "schedule_id": schedule_id,
                "membership_id": str(current.membership_id),
            },
        ).first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Schedule nao encontrado")
        self.db.commit()

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

    def _insert_source(
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
    ) -> Mapping[str, Any]:
        return self.db.execute(
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

    def _create_calibration_run(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
    ) -> dict[str, Any]:
        idempotency_key = (
            f"schedule-recalibrate:{segment_id}:"
            f"{datetime.now(UTC).replace(second=0, microsecond=0).isoformat()}"
        )
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
                  window_start_at,
                  started_at,
                  finished_at
                )
                VALUES (
                  :tenant_id,
                  :membership_id,
                  :segment_id,
                  'calibration',
                  'succeeded',
                  :idempotency_key,
                  :window_start_at,
                  NOW(),
                  NOW()
                )
                ON CONFLICT (tenant_id, run_type, idempotency_key)
                DO UPDATE SET updated_at = NOW()
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "membership_id": str(current.membership_id),
                "segment_id": segment_id,
                "idempotency_key": idempotency_key,
                "window_start_at": datetime.now(UTC).replace(second=0, microsecond=0),
            },
        ).mappings().one()
        return dict(row)

    def _schedule_buckets(self, *, tenant_id: str, segment_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT published_at, ranking_score
                FROM social_news_items
                WHERE tenant_id = :tenant_id
                  AND segment_id = :segment_id
                  AND published_at IS NOT NULL
                ORDER BY published_at DESC
                LIMIT 1000
                """
            ),
            {"tenant_id": tenant_id, "segment_id": segment_id},
        ).mappings().all()
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
        grouped: dict[tuple[int, int], list[float]] = {}
        for row in rows:
            published_at = _coerce_datetime(row["published_at"])
            if not published_at or published_at < cutoff:
                continue
            local_dt = published_at.replace(tzinfo=UTC).astimezone(
                ZoneInfo(DEFAULT_SCHEDULE_TIMEZONE)
            )
            key = (local_dt.weekday(), (local_dt.hour // 4) * 4)
            grouped.setdefault(key, []).append(float(row.get("ranking_score") or 0))

        buckets = []
        for (day, hour), scores in grouped.items():
            average_score = sum(scores) / len(scores)
            confidence_score = 45 + min(40, average_score / 150) + min(15, len(scores) * 3)
            buckets.append(
                {
                    "day_of_week": day,
                    "window_start_hour": hour,
                    "samples_count": len(scores),
                    "average_score": average_score,
                    "max_score": max(scores),
                    "confidence_score": round(min(99, confidence_score), 2),
                }
            )
        return sorted(
            buckets,
            key=lambda bucket: (bucket["confidence_score"], bucket["max_score"]),
            reverse=True,
        )

    def _upsert_schedule(
        self,
        *,
        current: CurrentMembership,
        segment_id: str,
        day_of_week: int | None,
        window_start_hour: int,
        window_end_hour: int,
        scheduled_hour: int,
        scheduled_minute: int,
        confidence_score: float,
        samples_count: int,
        average_score: float | None,
        discovered_by: str,
        origin_run_id: str,
        name: str,
    ) -> None:
        existing = self._find_schedule(
            tenant_id=str(current.tenant_id),
            segment_id=segment_id,
            day_of_week=day_of_week,
            window_start_hour=window_start_hour,
        )
        payload = {
            "tenant_id": str(current.tenant_id),
            "segment_id": segment_id,
            "name": name,
            "timezone": DEFAULT_SCHEDULE_TIMEZONE,
            "day_of_week": day_of_week,
            "window_start_hour": window_start_hour,
            "window_end_hour": window_end_hour,
            "scheduled_hour": scheduled_hour,
            "scheduled_minute": scheduled_minute,
            "confidence_score": confidence_score,
            "samples_count": samples_count,
            "average_score": average_score,
            "discovered_by": discovered_by,
            "origin_run_id": origin_run_id,
            "next_run_at": _next_schedule_run_at(
                {
                    "timezone": DEFAULT_SCHEDULE_TIMEZONE,
                    "day_of_week": day_of_week,
                    "scheduled_hour": scheduled_hour,
                    "scheduled_minute": scheduled_minute,
                }
            ),
            "membership_id": str(current.membership_id),
        }
        if existing:
            self.db.execute(
                text(
                    """
                    UPDATE social_news_schedules
                    SET name = :name,
                        window_end_hour = :window_end_hour,
                        scheduled_hour = :scheduled_hour,
                        scheduled_minute = :scheduled_minute,
                        confidence_score = :confidence_score,
                        samples_count = :samples_count,
                        average_score = :average_score,
                        discovered_by = :discovered_by,
                        origin_run_id = :origin_run_id,
                        status = 'active',
                        next_run_at = :next_run_at,
                        updated_by_membership_id = :membership_id,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :schedule_id
                    """
                ),
                {**payload, "schedule_id": str(existing["id"])},
            )
            return

        self.db.execute(
            text(
                """
                INSERT INTO social_news_schedules (
                  tenant_id,
                  segment_id,
                  name,
                  timezone,
                  day_of_week,
                  window_start_hour,
                  window_end_hour,
                  scheduled_hour,
                  scheduled_minute,
                  confidence_score,
                  samples_count,
                  average_score,
                  discovered_by,
                  origin_run_id,
                  status,
                  next_run_at,
                  created_by_membership_id,
                  updated_by_membership_id
                )
                VALUES (
                  :tenant_id,
                  :segment_id,
                  :name,
                  :timezone,
                  :day_of_week,
                  :window_start_hour,
                  :window_end_hour,
                  :scheduled_hour,
                  :scheduled_minute,
                  :confidence_score,
                  :samples_count,
                  :average_score,
                  :discovered_by,
                  :origin_run_id,
                  'active',
                  :next_run_at,
                  :membership_id,
                  :membership_id
                )
                """
            ),
            payload,
        )

    def _find_schedule(
        self,
        *,
        tenant_id: str,
        segment_id: str,
        day_of_week: int | None,
        window_start_hour: int,
    ) -> dict[str, Any] | None:
        if day_of_week is None:
            day_clause = "day_of_week IS NULL"
            day_params: dict[str, Any] = {}
        else:
            day_clause = "day_of_week = :day_of_week"
            day_params = {"day_of_week": day_of_week}
        row = self.db.execute(
            text(
                f"""
                SELECT *
                FROM social_news_schedules
                WHERE tenant_id = :tenant_id
                  AND segment_id = :segment_id
                  AND {day_clause}
                  AND window_start_hour = :window_start_hour
                ORDER BY
                  CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                  id DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "segment_id": segment_id,
                "window_start_hour": window_start_hour,
                **day_params,
            },
        ).mappings().first()
        return dict(row) if row else None

    def _get_schedule(self, tenant_id: UUID, schedule_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_news_schedules
                WHERE tenant_id = :tenant_id
                  AND id = :schedule_id
                """
            ),
            {"tenant_id": str(tenant_id), "schedule_id": schedule_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule nao encontrado")
        return dict(row)

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

    def _enqueue_rewrite_job(
        self,
        *,
        tenant_id: str,
        membership_id: str,
        item: Mapping[str, Any],
        idempotency_key: str,
        commit: bool = True,
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
            commit=commit,
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


def _is_placeholder(value: str) -> bool:
    return value.startswith("_PENDING_USER_INPUT_")


def _schedule_name(day_of_week: int, hour: int) -> str:
    labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    return f"{labels[day_of_week]} {hour:02d}:00-{min(hour + 4, 24):02d}:00"


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _next_schedule_run_at(
    schedule: Mapping[str, Any],
    *,
    after: datetime | None = None,
) -> datetime:
    tz_name = str(schedule.get("timezone") or DEFAULT_SCHEDULE_TIMEZONE)
    base_utc = (after or datetime.now(UTC)).astimezone(UTC)
    base_local = base_utc.astimezone(ZoneInfo(tz_name))
    hour = int(schedule.get("scheduled_hour") or 0)
    minute = int(schedule.get("scheduled_minute") or 0)
    day_of_week = schedule.get("day_of_week")

    if day_of_week is None:
        candidate = base_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= base_local:
            candidate += timedelta(days=1)
    else:
        wanted = int(day_of_week)
        days_ahead = (wanted - base_local.weekday()) % 7
        candidate = (base_local + timedelta(days=days_ahead)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate <= base_local:
            candidate += timedelta(days=7)

    return candidate.astimezone(UTC)
