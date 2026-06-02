import uuid
from math import ceil
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentMembership
from app.domains.jobs.job_service import JobQueueService

SALES_CAMPAIGN_DISPATCH_JOB = "sales.campaign.dispatch"
SALES_CAMPAIGN_QUEUE = "worker-sales-campaigns"


class SalesCampaignService:
    def __init__(self, db: Session, *, job_queue: JobQueueService | None = None) -> None:
        self.db = db
        self.job_queue = job_queue or JobQueueService(db)

    def list_campaigns(
        self,
        *,
        current: CurrentMembership,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        where = ["c.tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(current.tenant_id)}
        if status:
            where.append("c.status = :status")
            params["status"] = status
        where_sql = " AND ".join(where)
        total = self.db.execute(
            text(f"SELECT COUNT(*) FROM sales_campaigns c WHERE {where_sql}"),
            params,
        ).scalar_one()
        params.update({"limit": per_page, "offset": (page - 1) * per_page})
        rows = (
            self.db.execute(
                text(
                    f"""
                    SELECT
                        c.*,
                        ch.channel_type AS channel_tipo
                    FROM sales_campaigns c
                    LEFT JOIN sales_channels ch
                      ON ch.id = c.channel_id
                     AND ch.tenant_id = c.tenant_id
                    WHERE {where_sql}
                    ORDER BY c.created_at DESC, c.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
        return {
            "campaigns": [self._campaign_list_row(row) for row in rows],
            "total": int(total or 0),
            "page": page,
            "per_page": per_page,
            "pages": max(1, ceil(int(total or 0) / per_page)) if per_page else 1,
        }

    def get_campaign(self, *, current: CurrentMembership, campaign_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        row = self._campaign_row(tenant_id=str(current.tenant_id), campaign_id=campaign_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Campanha nao encontrada")
        return self._campaign_detail_row(row)

    def create_campaign(
        self,
        *,
        current: CurrentMembership,
        nome: str,
        conteudo: str,
        descricao: str | None = None,
        channel_id: str | None = None,
        tipo_mensagem: str = "text",
        contact_ids: list[str] | None = None,
        scheduled_at=None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        selected_channel_id = self._validate_channel(
            tenant_id=str(current.tenant_id),
            channel_id=channel_id,
        )
        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_campaigns (
                        tenant_id, channel_id, name, description, message_type,
                        content, status, idempotency_key, scheduled_at,
                        created_by_membership_id, updated_by_membership_id
                    )
                    VALUES (
                        :tenant_id, :channel_id, :name, :description, :message_type,
                        :content, :status, :idempotency_key, :scheduled_at,
                        :membership_id, :membership_id
                    )
                    ON CONFLICT (tenant_id, idempotency_key)
                    DO UPDATE SET idempotency_key = sales_campaigns.idempotency_key
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "channel_id": selected_channel_id,
                    "membership_id": str(current.membership_id),
                    "name": self._required_string(nome, "Nome da campanha e obrigatorio"),
                    "description": self._optional_string(descricao),
                    "message_type": tipo_mensagem,
                    "content": self._required_string(
                        conteudo,
                        "Conteudo da campanha e obrigatorio",
                    ),
                    "status": "scheduled" if scheduled_at else "draft",
                    "scheduled_at": scheduled_at,
                    "idempotency_key": self._idempotency_key(idempotency_key),
                },
            )
            .mappings()
            .one()
        )
        if contact_ids:
            self._add_recipients(
                current=current,
                campaign_id=str(row["id"]),
                contact_ids=contact_ids,
                commit=False,
            )
            row = self._campaign_row(tenant_id=str(current.tenant_id), campaign_id=str(row["id"]))
        self.db.commit()
        return self._mutation_row(row, message="Campanha criada")

    def update_campaign(
        self,
        *,
        current: CurrentMembership,
        campaign_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        updates = ["updated_by_membership_id = :membership_id", "updated_at = NOW()"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "campaign_id": UUID(str(campaign_id)),
            "membership_id": str(current.membership_id),
        }
        if "nome" in patch:
            updates.append("name = :name")
            params["name"] = self._required_string(patch["nome"], "Nome nao pode ser vazio")
        if "conteudo" in patch:
            updates.append("content = :content")
            params["content"] = self._required_string(
                patch["conteudo"],
                "Conteudo nao pode ser vazio",
            )
        if "descricao" in patch:
            updates.append("description = :description")
            params["description"] = self._optional_string(patch["descricao"])
        if "tipo_mensagem" in patch:
            updates.append("message_type = :message_type")
            params["message_type"] = patch["tipo_mensagem"]
        if "status" in patch:
            updates.append("status = :status")
            params["status"] = patch["status"]
        if "scheduled_at" in patch:
            updates.append("scheduled_at = :scheduled_at")
            params["scheduled_at"] = patch["scheduled_at"]
        if "channel_id" in patch:
            updates.append("channel_id = :channel_id")
            params["channel_id"] = self._validate_channel(
                tenant_id=str(current.tenant_id),
                channel_id=str(patch["channel_id"]) if patch["channel_id"] else None,
            )
        if len(updates) == 2:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        row = (
            self.db.execute(
                text(
                    f"""
                    UPDATE sales_campaigns
                    SET {", ".join(updates)}
                    WHERE tenant_id = :tenant_id
                      AND id = :campaign_id
                    RETURNING *
                    """
                ),
                params,
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Campanha nao encontrada")
        self.db.commit()
        return self._mutation_row(row, message="Campanha atualizada")

    def delete_campaign(self, *, current: CurrentMembership, campaign_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    DELETE FROM sales_campaigns
                    WHERE tenant_id = :tenant_id
                      AND id = :campaign_id
                      AND status IN ('draft', 'ativa', 'scheduled', 'paused', 'cancelled')
                    RETURNING id
                    """
                ),
                {"tenant_id": str(current.tenant_id), "campaign_id": UUID(str(campaign_id))},
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(
                status_code=404,
                detail="Campanha nao encontrada ou ja em processamento",
            )
        self.db.commit()
        return {"id": row["id"], "message": "Campanha removida"}

    def add_recipients(
        self,
        *,
        current: CurrentMembership,
        campaign_id: str,
        contact_ids: list[str],
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        result = self._add_recipients(
            current=current,
            campaign_id=campaign_id,
            contact_ids=contact_ids,
            commit=True,
        )
        return result

    def list_recipients(
        self,
        *,
        current: CurrentMembership,
        campaign_id: str,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._require_campaign(tenant_id=str(current.tenant_id), campaign_id=campaign_id)
        total = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sales_campaign_recipients
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                """
            ),
            {"tenant_id": str(current.tenant_id), "campaign_id": UUID(str(campaign_id))},
        ).scalar_one()
        rows = (
            self.db.execute(
                text(
                    """
                    SELECT
                        r.*,
                        c.name AS contact_name,
                        c.phone AS contact_phone
                    FROM sales_campaign_recipients r
                    LEFT JOIN sales_contacts c
                      ON c.id = r.contact_id
                     AND c.tenant_id = r.tenant_id
                    WHERE r.tenant_id = :tenant_id
                      AND r.campaign_id = :campaign_id
                    ORDER BY r.created_at ASC, r.id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "campaign_id": UUID(str(campaign_id)),
                    "limit": per_page,
                    "offset": (page - 1) * per_page,
                },
            )
            .mappings()
            .all()
        )
        return {
            "recipients": [self._recipient_row(row) for row in rows],
            "total": int(total or 0),
            "page": page,
            "per_page": per_page,
            "pages": max(1, ceil(int(total or 0) / per_page)) if per_page else 1,
        }

    def preview_recipients(
        self,
        *,
        current: CurrentMembership,
        campaign_id: str,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._require_campaign(tenant_id=str(current.tenant_id), campaign_id=campaign_id)
        total = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sales_campaign_recipients
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                """
            ),
            {"tenant_id": str(current.tenant_id), "campaign_id": UUID(str(campaign_id))},
        ).scalar_one()
        rows = (
            self.db.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.name,
                        c.phone,
                        c.email_normalized,
                        c.group_name
                    FROM sales_campaign_recipients r
                    JOIN sales_contacts c
                      ON c.id = r.contact_id
                     AND c.tenant_id = r.tenant_id
                    WHERE r.tenant_id = :tenant_id
                      AND r.campaign_id = :campaign_id
                    ORDER BY c.name ASC, c.id ASC
                    LIMIT 50
                    """
                ),
                {"tenant_id": str(current.tenant_id), "campaign_id": UUID(str(campaign_id))},
            )
            .mappings()
            .all()
        )
        return {
            "contacts": [
                {
                    "id": row["id"],
                    "nome": row["name"] or "Sem nome",
                    "telefone": row["phone"],
                    "email": row["email_normalized"],
                    "grupo": row["group_name"],
                }
                for row in rows
            ],
            "total": int(total or 0),
        }

    def start_campaign(self, *, current: CurrentMembership, campaign_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        campaign = self._require_campaign(
            tenant_id=str(current.tenant_id),
            campaign_id=campaign_id,
            for_update=True,
        )
        if campaign["status"] not in {"draft", "paused"}:
            raise HTTPException(
                status_code=400,
                detail="Apenas campanhas em rascunho ou pausadas podem ser iniciadas",
            )
        if int(campaign["total_recipients"] or 0) <= 0:
            raise HTTPException(status_code=400, detail="Campanha sem destinatarios")
        row = (
            self.db.execute(
                text(
                    """
                    UPDATE sales_campaigns
                    SET status = 'ativa',
                        started_at = COALESCE(started_at, NOW()),
                        updated_by_membership_id = :membership_id,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :campaign_id
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "campaign_id": UUID(str(campaign_id)),
                    "membership_id": str(current.membership_id),
                },
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return self._mutation_row(row, message="Campanha iniciada")

    def cancel_campaign(self, *, current: CurrentMembership, campaign_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        campaign = self._require_campaign(
            tenant_id=str(current.tenant_id),
            campaign_id=campaign_id,
            for_update=True,
        )
        if campaign["status"] in {"cancelled", "queued", "sent"}:
            raise HTTPException(status_code=400, detail="Campanha ja esta finalizada")
        row = (
            self.db.execute(
                text(
                    """
                    UPDATE sales_campaigns
                    SET status = 'cancelled',
                        updated_by_membership_id = :membership_id,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :campaign_id
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "campaign_id": UUID(str(campaign_id)),
                    "membership_id": str(current.membership_id),
                },
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return self._mutation_row(row, message="Campanha cancelada")

    def dispatch_campaign(
        self,
        *,
        current: CurrentMembership,
        campaign_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        campaign = self._require_campaign(
            tenant_id=str(current.tenant_id),
            campaign_id=campaign_id,
            for_update=True,
        )
        if campaign["status"] not in {"ativa", "sending", "failed"}:
            raise HTTPException(
                status_code=400,
                detail="Campanha precisa estar ativa para disparar. Use /start primeiro.",
            )
        if int(campaign["total_recipients"] or 0) <= 0:
            raise HTTPException(status_code=400, detail="Campanha sem destinatarios")

        selected_idempotency_key = (
            self._optional_string(idempotency_key)
            or f"sales.campaign.dispatch:{campaign_id}:v1"
        )
        duplicate = self._job_exists(
            tenant_id=str(current.tenant_id),
            job_type=SALES_CAMPAIGN_DISPATCH_JOB,
            idempotency_key=selected_idempotency_key,
        )
        self.db.execute(
            text(
                """
                UPDATE sales_campaigns
                SET status = CASE
                        WHEN status IN ('sent', 'queued') THEN status
                        ELSE 'sending'
                    END,
                    started_at = COALESCE(started_at, NOW()),
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :campaign_id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "campaign_id": UUID(str(campaign_id)),
                "membership_id": str(current.membership_id),
            },
        )
        job = self.job_queue.enqueue_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            job_type=SALES_CAMPAIGN_DISPATCH_JOB,
            queue_name=SALES_CAMPAIGN_QUEUE,
            idempotency_key=selected_idempotency_key,
            payload={"campaign_id": campaign_id},
            max_attempts=3,
            commit=False,
        )
        self.db.commit()
        refreshed = self._require_campaign(
            tenant_id=str(current.tenant_id),
            campaign_id=campaign_id,
        )
        return {
            "campaign_id": UUID(str(campaign_id)),
            "status": refreshed["status"],
            "job_id": UUID(str(job.id)),
            "job_type": job.job_type,
            "idempotency_key": job.idempotency_key,
            "duplicate": duplicate,
        }

    def _add_recipients(
        self,
        *,
        current: CurrentMembership,
        campaign_id: str,
        contact_ids: list[str],
        commit: bool,
    ) -> dict[str, Any]:
        self._require_campaign(tenant_id=str(current.tenant_id), campaign_id=campaign_id)
        unique_contact_ids = list(dict.fromkeys(str(contact_id) for contact_id in contact_ids))
        if not unique_contact_ids:
            raise HTTPException(status_code=400, detail="Informe ao menos um contato")
        row = self.db.execute(
            text(
                """
                WITH requested AS (
                    SELECT DISTINCT unnest(CAST(:contact_ids AS uuid[])) AS contact_id
                ),
                eligible AS (
                    SELECT
                        c.id,
                        c.name,
                        c.phone_normalized
                    FROM requested r
                    JOIN sales_contacts c
                      ON c.id = r.contact_id
                     AND c.tenant_id = :tenant_id
                    WHERE c.status = 'active'
                      AND c.optout = false
                ),
                inserted AS (
                    INSERT INTO sales_campaign_recipients (
                        tenant_id, campaign_id, contact_id, recipient_name,
                        phone_normalized, metadata
                    )
                    SELECT
                        :tenant_id,
                        :campaign_id,
                        e.id,
                        e.name,
                        e.phone_normalized,
                        '{}'::jsonb
                    FROM eligible e
                    ON CONFLICT (tenant_id, campaign_id, contact_id)
                        WHERE contact_id IS NOT NULL
                    DO NOTHING
                    RETURNING id
                )
                SELECT
                    (SELECT COUNT(*) FROM requested) AS requested,
                    (SELECT COUNT(*) FROM eligible) AS eligible,
                    (SELECT COUNT(*) FROM inserted) AS inserted
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "campaign_id": UUID(str(campaign_id)),
                "contact_ids": unique_contact_ids,
            },
        ).mappings().one()
        total_destinatarios = self._sync_campaign_counts(
            tenant_id=str(current.tenant_id),
            campaign_id=campaign_id,
        )["total_recipients"]
        if commit:
            self.db.commit()
        requested = int(row["requested"] or 0)
        eligible = int(row["eligible"] or 0)
        inserted = int(row["inserted"] or 0)
        return {
            "campaign_id": UUID(str(campaign_id)),
            "requested": requested,
            "inserted": inserted,
            "duplicates": max(0, eligible - inserted),
            "invalid_or_optout": max(0, requested - eligible),
            "total_destinatarios": int(total_destinatarios or 0),
        }

    def _sync_campaign_counts(self, *, tenant_id: str, campaign_id: str):
        row = (
            self.db.execute(
                text(
                    """
                    WITH counts AS (
                        SELECT
                            COUNT(*) AS total_recipients,
                            COUNT(*) FILTER (WHERE status = 'queued') AS queued_count,
                            COUNT(*) FILTER (WHERE status = 'sent') AS sent_count,
                            COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                            COUNT(*) FILTER (WHERE status = 'skipped') AS skipped_count
                        FROM sales_campaign_recipients
                        WHERE tenant_id = :tenant_id
                          AND campaign_id = :campaign_id
                    )
                    UPDATE sales_campaigns c
                    SET total_recipients = counts.total_recipients,
                        queued_count = counts.queued_count,
                        sent_count = counts.sent_count,
                        failed_count = counts.failed_count,
                        skipped_count = counts.skipped_count,
                        updated_at = NOW()
                    FROM counts
                    WHERE c.tenant_id = :tenant_id
                      AND c.id = :campaign_id
                    RETURNING c.*
                    """
                ),
                {"tenant_id": tenant_id, "campaign_id": UUID(str(campaign_id))},
            )
            .mappings()
            .one()
        )
        return row

    def _campaign_row(self, *, tenant_id: str, campaign_id: str):
        return (
            self.db.execute(
                text(
                    """
                    SELECT c.*, ch.channel_type AS channel_tipo
                    FROM sales_campaigns c
                    LEFT JOIN sales_channels ch
                      ON ch.id = c.channel_id
                     AND ch.tenant_id = c.tenant_id
                    WHERE c.tenant_id = :tenant_id
                      AND c.id = :campaign_id
                    """
                ),
                {"tenant_id": tenant_id, "campaign_id": UUID(str(campaign_id))},
            )
            .mappings()
            .first()
        )

    def _require_campaign(self, *, tenant_id: str, campaign_id: str, for_update: bool = False):
        lock = "FOR UPDATE" if for_update else ""
        row = (
            self.db.execute(
                text(
                    f"""
                    SELECT *
                    FROM sales_campaigns
                    WHERE tenant_id = :tenant_id
                      AND id = :campaign_id
                    {lock}
                    """
                ),
                {"tenant_id": tenant_id, "campaign_id": UUID(str(campaign_id))},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Campanha nao encontrada")
        return row

    def _validate_channel(self, *, tenant_id: str, channel_id: str | None):
        if not channel_id:
            return None
        row = self.db.execute(
            text(
                """
                SELECT id
                FROM sales_channels
                WHERE tenant_id = :tenant_id
                  AND id = :channel_id
                """
            ),
            {"tenant_id": tenant_id, "channel_id": UUID(str(channel_id))},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        return UUID(str(channel_id))

    def _job_exists(self, *, tenant_id: str, job_type: str, idempotency_key: str) -> bool:
        return (
            self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM jobs
                    WHERE tenant_id = :tenant_id
                      AND job_type = :job_type
                      AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "job_type": job_type,
                    "idempotency_key": idempotency_key,
                },
            ).first()
            is not None
        )

    @staticmethod
    def _assert_sales_access(current: CurrentMembership) -> None:
        if current.role == "owner":
            return
        if "sales" not in current.modules:
            raise HTTPException(status_code=403, detail="Modulo sales nao habilitado")

    @staticmethod
    def _assert_write_access(current: CurrentMembership) -> None:
        if current.role not in {"owner", "admin", "agent"}:
            raise HTTPException(status_code=403, detail="Permissao insuficiente")

    @staticmethod
    def _campaign_list_row(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "nome": row["name"],
            "status": row["status"],
            "channel_id": row["channel_id"],
            "channel_tipo": row["channel_tipo"],
            "total_destinatarios": int(row["total_recipients"] or 0),
            "queued_count": int(row["queued_count"] or 0),
            "sent_count": int(row["sent_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
            "skipped_count": int(row["skipped_count"] or 0),
            "scheduled_at": row["scheduled_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _campaign_detail_row(cls, row) -> dict[str, Any]:
        data = cls._campaign_list_row(row)
        data.update(
            {
                "descricao": row["description"],
                "conteudo": row["content"],
                "tipo_mensagem": row["message_type"],
                "idempotency_key": row["idempotency_key"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
        )
        return data

    @staticmethod
    def _recipient_row(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "contact_id": row["contact_id"],
            "contato_nome": row["contact_name"] or row["recipient_name"],
            "telefone": row["contact_phone"] or row["phone_normalized"],
            "status": row["status"],
            "message_id": row["message_id"],
            "conversation_id": row["conversation_id"],
            "error": row["error"],
            "queued_at": row["queued_at"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _mutation_row(row, *, message: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "nome": row["name"],
            "status": row["status"],
            "total_destinatarios": int(row["total_recipients"] or 0),
            "message": message,
        }

    @staticmethod
    def _idempotency_key(value: str | None) -> str:
        cleaned = str(value or "").strip()
        return cleaned or f"campaign:{uuid.uuid4()}"

    @staticmethod
    def _required_string(value: str | None, message: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail=message)
        return cleaned

    @staticmethod
    def _optional_string(value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None
