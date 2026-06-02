from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentMembership


class SalesAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def dashboard(self, *, current: CurrentMembership) -> dict[str, Any]:
        self._assert_sales_access(current)
        tenant_id = str(current.tenant_id)
        row = self.db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE m.created_at >= DATE_TRUNC('day', NOW())
                    ) AS mensagens_hoje,
                    COUNT(*) FILTER (
                        WHERE m.created_at >= NOW() - INTERVAL '7 days'
                    ) AS mensagens_semana,
                    COUNT(*) FILTER (
                        WHERE m.created_at >= NOW() - INTERVAL '7 days'
                          AND m.direction = 'entrada'
                    ) AS entrada_semana,
                    COUNT(*) FILTER (
                        WHERE m.created_at >= NOW() - INTERVAL '7 days'
                          AND m.direction = 'saida'
                    ) AS saida_semana
                FROM sales_messages m
                WHERE m.tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
        contatos_total = self.db.execute(
            text("SELECT COUNT(*) FROM sales_contacts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
        conversas_abertas = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sales_conversations
                WHERE tenant_id = :tenant_id
                  AND status = 'aberta'
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one()
        campanhas_ativas = self._active_campaigns_count(tenant_id)
        entrada = int(row["entrada_semana"] or 0)
        saida = int(row["saida_semana"] or 0)
        taxa_resposta = round((saida / entrada) * 100, 1) if entrada else 0.0
        return {
            "mensagens_hoje": int(row["mensagens_hoje"] or 0),
            "mensagens_semana": int(row["mensagens_semana"] or 0),
            "contatos_total": int(contatos_total or 0),
            "conversas_abertas": int(conversas_abertas or 0),
            "campanhas_ativas": campanhas_ativas,
            "taxa_resposta": taxa_resposta,
        }

    def message_volume(self, *, current: CurrentMembership, period: str = "7d") -> dict[str, Any]:
        self._assert_sales_access(current)
        days = {"7d": 7, "30d": 30, "90d": 90}[period]
        rows = (
            self.db.execute(
                text(
                    """
                    WITH days AS (
                        SELECT generate_series(
                            CURRENT_DATE - (:days_back * INTERVAL '1 day'),
                            CURRENT_DATE,
                            INTERVAL '1 day'
                        )::date AS day
                    )
                    SELECT
                        days.day AS date,
                        COUNT(m.id) FILTER (WHERE m.direction = 'saida') AS enviadas,
                        COUNT(m.id) FILTER (WHERE m.direction = 'entrada') AS recebidas
                    FROM days
                    LEFT JOIN sales_messages m
                      ON m.tenant_id = :tenant_id
                     AND m.created_at::date = days.day
                    GROUP BY days.day
                    ORDER BY days.day ASC
                    """
                ),
                {"tenant_id": str(current.tenant_id), "days_back": days - 1},
            )
            .mappings()
            .all()
        )
        return {
            "period": period,
            "data": [
                {
                    "date": row["date"].isoformat()
                    if hasattr(row["date"], "isoformat")
                    else str(row["date"]),
                    "enviadas": int(row["enviadas"] or 0),
                    "recebidas": int(row["recebidas"] or 0),
                }
                for row in rows
            ],
        }

    def recent_activity(
        self,
        *,
        current: CurrentMembership,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._assert_sales_access(current)
        rows = (
            self.db.execute(
                text(
                    """
                    WITH recent AS (
                        SELECT
                            c.id,
                            c.status,
                            c.waiting_for_human,
                            c.last_message_at,
                            c.created_at,
                            ct.name AS contact_name,
                            ch.channel_type
                        FROM sales_conversations c
                        JOIN sales_contacts ct
                          ON ct.id = c.contact_id
                         AND ct.tenant_id = c.tenant_id
                        LEFT JOIN sales_channels ch
                          ON ch.id = c.channel_id
                         AND ch.tenant_id = c.tenant_id
                        WHERE c.tenant_id = :tenant_id
                          AND c.last_message_at IS NOT NULL
                        ORDER BY c.last_message_at DESC, c.id DESC
                        LIMIT :limit
                    ),
                    last_messages AS (
                        SELECT DISTINCT ON (m.conversation_id)
                            m.conversation_id,
                            m.content
                        FROM sales_messages m
                        JOIN recent r ON r.id = m.conversation_id
                        WHERE m.tenant_id = :tenant_id
                        ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
                    )
                    SELECT recent.*, last_messages.content AS last_message
                    FROM recent
                    LEFT JOIN last_messages ON last_messages.conversation_id = recent.id
                    ORDER BY recent.last_message_at DESC, recent.id DESC
                    """
                ),
                {"tenant_id": str(current.tenant_id), "limit": limit},
            )
            .mappings()
            .all()
        )
        return [
            {
                "tipo": "conversa",
                "titulo": row["contact_name"] or "Contato",
                "descricao": row["last_message"],
                "canal": row["channel_type"],
                "timestamp": row["last_message_at"],
                "link_id": row["id"],
                "status": row["status"] or "aberta",
                "aguardando_humano": bool(row["waiting_for_human"]),
            }
            for row in rows
        ]

    def _active_campaigns_count(self, tenant_id: str) -> int:
        table_exists = self.db.execute(
            text("SELECT to_regclass('public.sales_campaigns') IS NOT NULL")
        ).scalar_one()
        if not table_exists:
            return 0
        return int(
            self.db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM sales_campaigns
                    WHERE tenant_id = :tenant_id
                      AND status IN ('ativa', 'sending', 'scheduled')
                    """
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
            or 0
        )

    @staticmethod
    def _assert_sales_access(current: CurrentMembership) -> None:
        if current.role == "owner":
            return
        if "sales" not in current.modules:
            raise HTTPException(status_code=403, detail="Modulo sales nao habilitado")
