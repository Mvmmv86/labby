import json
from math import ceil
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentMembership
from app.domains.jobs.job_service import JobQueueService
from app.domains.sales.outbound_service import enqueue_sales_message_dispatch


class SalesConversationService:
    def __init__(self, db: Session, *, job_queue: JobQueueService | None = None) -> None:
        self.db = db
        self.job_queue = job_queue or JobQueueService(db)

    def list_conversations(
        self,
        *,
        current: CurrentMembership,
        channel_tipo: str | None = None,
        status: str | None = None,
        search: str | None = None,
        atendente_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        where_clauses = ["c.tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(current.tenant_id)}

        if channel_tipo:
            where_clauses.append("ch.channel_type = :channel_tipo")
            params["channel_tipo"] = channel_tipo

        if status:
            where_clauses.append("c.status = :status")
            params["status"] = status

        if atendente_id:
            where_clauses.append("c.assigned_to_membership_id = :atendente_id")
            params["atendente_id"] = atendente_id

        if search:
            where_clauses.append(
                """
                (
                    ct.name ILIKE :search
                    OR ct.phone ILIKE :search
                    OR ct.phone_normalized ILIKE :search
                    OR EXISTS (
                        SELECT 1
                        FROM sales_messages sm
                        WHERE sm.conversation_id = c.id
                          AND sm.tenant_id = c.tenant_id
                          AND sm.content ILIKE :search
                    )
                )
                """
            )
            params["search"] = f"%{search.strip()}%"

        where_sql = " AND ".join(where_clauses)
        total = self.db.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM sales_conversations c
                JOIN sales_contacts ct
                  ON ct.id = c.contact_id
                 AND ct.tenant_id = c.tenant_id
                LEFT JOIN sales_channels ch
                  ON ch.id = c.channel_id
                 AND ch.tenant_id = c.tenant_id
                WHERE {where_sql}
                """
            ),
            params,
        ).scalar_one()

        params.update({"limit": per_page, "offset": (page - 1) * per_page})
        rows = (
            self.db.execute(
                text(
                    f"""
                    WITH page_conversations AS (
                        SELECT
                            c.id, c.contact_id, c.status, c.subject, c.tags, c.bot_active,
                            c.waiting_for_human, c.assigned_to_membership_id,
                            c.last_message_at, c.created_at, c.channel_id,
                            ct.name AS contact_name,
                            ct.phone AS contact_phone,
                            ch.channel_type,
                            ch.name AS channel_name,
                            u.nome AS assigned_name
                        FROM sales_conversations c
                        JOIN sales_contacts ct
                          ON ct.id = c.contact_id
                         AND ct.tenant_id = c.tenant_id
                        LEFT JOIN sales_channels ch
                          ON ch.id = c.channel_id
                         AND ch.tenant_id = c.tenant_id
                        LEFT JOIN memberships am
                          ON am.id = c.assigned_to_membership_id
                         AND am.tenant_id = c.tenant_id
                        LEFT JOIN users u ON u.id = am.user_id
                        WHERE {where_sql}
                        ORDER BY
                            c.last_message_at DESC NULLS LAST,
                            c.created_at DESC,
                            c.id DESC
                        LIMIT :limit OFFSET :offset
                    ),
                    last_messages AS (
                        SELECT DISTINCT ON (m.conversation_id)
                            m.conversation_id,
                            m.content,
                            m.created_at
                        FROM sales_messages m
                        JOIN page_conversations p ON p.id = m.conversation_id
                        WHERE m.tenant_id = :tenant_id
                        ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
                    ),
                    unread_counts AS (
                        SELECT
                            m.conversation_id,
                            COUNT(*) AS unread_count
                        FROM sales_messages m
                        JOIN page_conversations p ON p.id = m.conversation_id
                        WHERE m.tenant_id = :tenant_id
                          AND m.direction = 'entrada'
                          AND m.status != 'read'
                        GROUP BY m.conversation_id
                    )
                    SELECT
                        p.*,
                        lm.content AS last_message,
                        COALESCE(lm.created_at, p.last_message_at) AS effective_last_message_at,
                        COALESCE(uc.unread_count, 0) AS unread_count
                    FROM page_conversations p
                    LEFT JOIN last_messages lm ON lm.conversation_id = p.id
                    LEFT JOIN unread_counts uc ON uc.conversation_id = p.id
                    ORDER BY
                        p.last_message_at DESC NULLS LAST,
                        p.created_at DESC,
                        p.id DESC
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )

        return {
            "conversations": [self._conversation_list_row(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, ceil(total / per_page)) if per_page else 1,
        }

    def notification_summary(self, *, current: CurrentMembership) -> dict[str, Any]:
        self._assert_sales_access(current)
        params = {"tenant_id": str(current.tenant_id)}
        rows = (
            self.db.execute(
                text(
                    """
                    WITH awaiting AS (
                        SELECT
                            c.id,
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
                          AND c.waiting_for_human = true
                          AND c.status != 'fechada'
                        ORDER BY
                            c.last_message_at DESC NULLS LAST,
                            c.created_at DESC,
                            c.id DESC
                        LIMIT 50
                    ),
                    last_messages AS (
                        SELECT DISTINCT ON (m.conversation_id)
                            m.conversation_id,
                            m.content,
                            m.created_at
                        FROM sales_messages m
                        JOIN awaiting a ON a.id = m.conversation_id
                        WHERE m.tenant_id = :tenant_id
                        ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
                    ),
                    unread_counts AS (
                        SELECT
                            m.conversation_id,
                            COUNT(*) AS unread_count
                        FROM sales_messages m
                        JOIN awaiting a ON a.id = m.conversation_id
                        WHERE m.tenant_id = :tenant_id
                          AND m.direction = 'entrada'
                          AND m.status != 'read'
                        GROUP BY m.conversation_id
                    )
                    SELECT
                        a.id,
                        a.contact_name,
                        a.channel_type,
                        lm.content AS last_message,
                        COALESCE(lm.created_at, a.last_message_at) AS last_message_at,
                        COALESCE(uc.unread_count, 0) AS unread_count
                    FROM awaiting a
                    LEFT JOIN last_messages lm ON lm.conversation_id = a.id
                    LEFT JOIN unread_counts uc ON uc.conversation_id = a.id
                    ORDER BY
                        a.last_message_at DESC NULLS LAST,
                        a.created_at DESC,
                        a.id DESC
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
        total_unread = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sales_messages m
                JOIN sales_conversations c
                  ON c.id = m.conversation_id
                 AND c.tenant_id = m.tenant_id
                WHERE c.tenant_id = :tenant_id
                  AND c.status != 'fechada'
                  AND m.direction = 'entrada'
                  AND m.status != 'read'
                """
            ),
            params,
        ).scalar_one()
        total_waiting = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sales_conversations c
                WHERE c.tenant_id = :tenant_id
                  AND c.waiting_for_human = true
                  AND c.status != 'fechada'
                """
            ),
            params,
        ).scalar_one()

        return {
            "transferencias_pendentes": int(total_waiting or 0),
            "total_nao_lidas": int(total_unread or 0),
            "conversas_aguardando": [
                {
                    "id": row["id"],
                    "contato_nome": row["contact_name"] or "Desconhecido",
                    "channel_tipo": row["channel_type"],
                    "ultima_mensagem": row["last_message"],
                    "ultima_mensagem_at": row["last_message_at"],
                    "mensagens_nao_lidas": int(row["unread_count"] or 0),
                }
                for row in rows
            ],
        }

    def get_conversation(
        self,
        *,
        current: CurrentMembership,
        conversation_id: str,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        conversation_uuid = UUID(str(conversation_id))
        row = (
            self.db.execute(
                text(
                    """
                    SELECT
                        c.id, c.status, c.subject, c.tags, c.bot_active,
                        c.assigned_to_membership_id, c.last_message_at, c.closed_at,
                        c.created_at, c.channel_id,
                        ct.id AS contact_id,
                        ct.name AS contact_name,
                        ct.phone AS contact_phone,
                        ct.email_normalized AS contact_email,
                        ct.tags AS contact_tags,
                        ct.group_name AS contact_group,
                        ct.notes AS contact_notes,
                        ct.last_interaction_at AS contact_last_interaction_at,
                        ct.created_at AS contact_created_at,
                        ch.channel_type,
                        ch.name AS channel_name,
                        u.nome AS assigned_name
                    FROM sales_conversations c
                    JOIN sales_contacts ct
                      ON ct.id = c.contact_id
                     AND ct.tenant_id = c.tenant_id
                    LEFT JOIN sales_channels ch
                      ON ch.id = c.channel_id
                     AND ch.tenant_id = c.tenant_id
                    LEFT JOIN memberships am
                      ON am.id = c.assigned_to_membership_id
                     AND am.tenant_id = c.tenant_id
                    LEFT JOIN users u ON u.id = am.user_id
                    WHERE c.id = :conversation_id
                      AND c.tenant_id = :tenant_id
                    """
                ),
                {"conversation_id": conversation_uuid, "tenant_id": str(current.tenant_id)},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Conversa nao encontrada")
        return self._conversation_detail_row(row)

    def update_conversation(
        self,
        *,
        current: CurrentMembership,
        conversation_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        updates = ["updated_by_membership_id = :membership_id", "updated_at = now()"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "membership_id": str(current.membership_id),
            "conversation_id": UUID(str(conversation_id)),
        }

        if "status" in patch:
            updates.append("status = :status")
            params["status"] = patch["status"]
            if patch["status"] == "fechada":
                updates.append("closed_at = COALESCE(closed_at, now())")
            else:
                updates.append("closed_at = NULL")

        if "atendente_id" in patch:
            assigned_to = patch["atendente_id"]
            if assigned_to is not None:
                self._assert_membership_in_tenant(
                    tenant_id=str(current.tenant_id),
                    membership_id=str(assigned_to),
                )
            updates.append("assigned_to_membership_id = :assigned_to_membership_id")
            params["assigned_to_membership_id"] = str(assigned_to) if assigned_to else None

        if "tags" in patch:
            updates.append("tags = CAST(:tags AS jsonb)")
            params["tags"] = self._json_array(self._clean_tags(patch["tags"]))

        if "assunto" in patch:
            updates.append("subject = :subject")
            params["subject"] = self._optional_string(patch["assunto"])

        if len(updates) == 2:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        row = (
            self.db.execute(
                text(
                    f"""
                    UPDATE sales_conversations
                    SET {", ".join(updates)}
                    WHERE id = :conversation_id
                      AND tenant_id = :tenant_id
                    RETURNING id, status, assigned_to_membership_id, subject, tags
                    """
                ),
                params,
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Conversa nao encontrada")
        self.db.commit()
        return self._conversation_mutation_row(row, message="Conversa atualizada")

    def list_messages(
        self,
        *,
        current: CurrentMembership,
        conversation_id: str,
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_conversation_in_tenant(
            tenant_id=str(current.tenant_id), conversation_id=conversation_id
        )

        where_sql = "m.conversation_id = :conversation_id AND m.tenant_id = :tenant_id"
        params: dict[str, Any] = {
            "conversation_id": UUID(str(conversation_id)),
            "tenant_id": str(current.tenant_id),
            "fetch_limit": limit + 1,
        }
        if cursor:
            cursor_row = (
                self.db.execute(
                    text(
                        """
                        SELECT id, created_at
                        FROM sales_messages
                        WHERE id = :cursor
                          AND conversation_id = :conversation_id
                          AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "cursor": cursor,
                        "conversation_id": UUID(str(conversation_id)),
                        "tenant_id": str(current.tenant_id),
                    },
                )
                .mappings()
                .first()
            )
            if cursor_row is None:
                raise HTTPException(status_code=400, detail="Cursor invalido")
            where_sql += """
                AND (
                    m.created_at < :cursor_created_at
                    OR (m.created_at = :cursor_created_at AND m.id < :cursor_id)
                )
            """
            params["cursor_created_at"] = cursor_row["created_at"]
            params["cursor_id"] = cursor_row["id"]

        rows = (
            self.db.execute(
                text(
                    f"""
                    SELECT
                        id, conversation_id, contact_id, direction, sender_type,
                        sender_membership_id, message_type, content, media_url,
                        media_caption, status, created_at
                    FROM sales_messages m
                    WHERE {where_sql}
                    ORDER BY m.created_at DESC, m.id DESC
                    LIMIT :fetch_limit
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        messages = [self._message_row(row) for row in visible_rows]
        return {
            "messages": messages,
            "has_more": has_more,
            "next_cursor": messages[-1]["id"] if messages and has_more else None,
        }

    def mark_read(self, *, current: CurrentMembership, conversation_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_conversation_in_tenant(
            tenant_id=str(current.tenant_id), conversation_id=conversation_id
        )
        result = self.db.execute(
            text(
                """
                UPDATE sales_messages
                SET status = 'read'
                WHERE conversation_id = :conversation_id
                  AND tenant_id = :tenant_id
                  AND direction = 'entrada'
                  AND status != 'read'
                """
            ),
            {
                "conversation_id": UUID(str(conversation_id)),
                "tenant_id": str(current.tenant_id),
            },
        )
        self.db.commit()
        return {"marked": result.rowcount}

    def send_message(
        self,
        *,
        current: CurrentMembership,
        conversation_id: str,
        conteudo: str,
        tipo: str = "text",
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        content = str(conteudo or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="Conteudo da mensagem nao pode ser vazio")

        conversation = (
            self.db.execute(
                text(
                    """
                    SELECT id, contact_id
                    FROM sales_conversations
                    WHERE id = :conversation_id
                      AND tenant_id = :tenant_id
                    FOR UPDATE
                    """
                ),
                {
                    "conversation_id": UUID(str(conversation_id)),
                    "tenant_id": str(current.tenant_id),
                },
            )
            .mappings()
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversa nao encontrada")

        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_messages (
                        tenant_id, conversation_id, contact_id, direction,
                        sender_type, sender_membership_id, message_type, content, status
                    )
                    VALUES (
                        :tenant_id, :conversation_id, :contact_id, 'saida',
                        'usuario', :membership_id, :message_type, :content, 'pending'
                    )
                    RETURNING
                        id, conversation_id, contact_id, direction, sender_type,
                        sender_membership_id, message_type, content, media_url,
                        media_caption, status, created_at
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "conversation_id": UUID(str(conversation_id)),
                    "contact_id": conversation["contact_id"],
                    "membership_id": str(current.membership_id),
                    "message_type": tipo,
                    "content": content,
                },
            )
            .mappings()
            .one()
        )
        self.db.execute(
            text(
                """
                UPDATE sales_conversations
                SET last_message_at = :created_at,
                    waiting_for_human = false,
                    status = CASE WHEN status = 'fechada' THEN 'aberta' ELSE status END,
                    updated_by_membership_id = :membership_id,
                    updated_at = now()
                WHERE id = :conversation_id
                  AND tenant_id = :tenant_id
                """
            ),
            {
                "created_at": row["created_at"],
                "membership_id": str(current.membership_id),
                "conversation_id": UUID(str(conversation_id)),
                "tenant_id": str(current.tenant_id),
            },
        )
        self.db.execute(
            text(
                """
                UPDATE sales_contacts
                SET total_messages_sent = total_messages_sent + 1,
                    last_interaction_at = :created_at,
                    updated_by_membership_id = :membership_id,
                    updated_at = now()
                WHERE id = :contact_id
                  AND tenant_id = :tenant_id
                """
            ),
            {
                "created_at": row["created_at"],
                "membership_id": str(current.membership_id),
                "contact_id": conversation["contact_id"],
                "tenant_id": str(current.tenant_id),
            },
        )
        enqueue_sales_message_dispatch(
            job_queue=self.job_queue,
            tenant_id=str(current.tenant_id),
            message_id=str(row["id"]),
            membership_id=str(current.membership_id),
            commit=False,
        )
        self.db.commit()
        return self._message_row(row)

    def close_conversation(
        self,
        *,
        current: CurrentMembership,
        conversation_id: str,
    ) -> dict[str, Any]:
        return self.update_conversation(
            current=current,
            conversation_id=conversation_id,
            patch={"status": "fechada"},
        ) | {"message": "Conversa fechada"}

    def _assert_conversation_in_tenant(self, *, tenant_id: str, conversation_id: str) -> None:
        row = self.db.execute(
            text(
                """
                SELECT id
                FROM sales_conversations
                WHERE id = :conversation_id
                  AND tenant_id = :tenant_id
                """
            ),
            {"conversation_id": UUID(str(conversation_id)), "tenant_id": tenant_id},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Conversa nao encontrada")

    def _assert_membership_in_tenant(self, *, tenant_id: str, membership_id: str) -> None:
        row = self.db.execute(
            text(
                """
                SELECT id
                FROM memberships
                WHERE id = :membership_id
                  AND tenant_id = :tenant_id
                  AND status = 'active'
                """
            ),
            {"membership_id": membership_id, "tenant_id": tenant_id},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Atendente nao encontrado")

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
    def _conversation_list_row(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "contato_id": row["contact_id"],
            "contato_nome": row["contact_name"] or "Desconhecido",
            "contato_telefone": row["contact_phone"],
            "channel_id": row["channel_id"],
            "channel_tipo": row["channel_type"],
            "channel_nome": row["channel_name"],
            "status": row["status"] or "aberta",
            "assunto": row["subject"],
            "tags": row["tags"] or [],
            "atendente_id": row["assigned_to_membership_id"],
            "atendente_nome": row["assigned_name"],
            "bot_ativo": row["bot_active"] or False,
            "aguardando_humano": row["waiting_for_human"] or False,
            "ultima_mensagem": row["last_message"],
            "ultima_mensagem_at": row["effective_last_message_at"],
            "mensagens_nao_lidas": int(row["unread_count"] or 0),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _conversation_detail_row(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "contato": {
                "id": row["contact_id"],
                "nome": row["contact_name"] or "Desconhecido",
                "telefone": row["contact_phone"],
                "email": row["contact_email"],
                "tags": row["contact_tags"] or [],
                "grupo": row["contact_group"],
                "notas": row["contact_notes"],
                "ultima_interacao": row["contact_last_interaction_at"],
                "created_at": row["contact_created_at"],
            },
            "channel": {
                "id": row["channel_id"],
                "tipo": row["channel_type"],
                "nome": row["channel_name"],
            },
            "status": row["status"] or "aberta",
            "assunto": row["subject"],
            "tags": row["tags"] or [],
            "atendente_id": row["assigned_to_membership_id"],
            "atendente_nome": row["assigned_name"],
            "bot_ativo": row["bot_active"] or False,
            "ultima_mensagem_at": row["last_message_at"],
            "fechado_at": row["closed_at"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _message_row(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "conversa_id": row["conversation_id"],
            "contato_id": row["contact_id"],
            "direcao": row["direction"],
            "remetente_tipo": row["sender_type"],
            "remetente_id": row["sender_membership_id"],
            "tipo": row["message_type"] or "text",
            "conteudo": row["content"] or "",
            "media_url": row["media_url"],
            "media_caption": row["media_caption"],
            "status": row["status"] or "pending",
            "created_at": row["created_at"],
        }

    @staticmethod
    def _conversation_mutation_row(row, *, message: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["status"],
            "atendente_id": row["assigned_to_membership_id"],
            "assunto": row["subject"],
            "tags": row["tags"] or [],
            "message": message,
        }

    @staticmethod
    def _clean_tags(raw_tags: Any) -> list[str]:
        if raw_tags is None:
            return []
        if isinstance(raw_tags, str):
            values = raw_tags.split(",")
        elif isinstance(raw_tags, list):
            values = raw_tags
        else:
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for tag in values:
            value = str(tag or "").strip()
            if value and value not in seen:
                cleaned.append(value)
                seen.add(value)
        return cleaned

    @staticmethod
    def _optional_string(value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    @staticmethod
    def _json_array(values: list[str]) -> str:
        return json.dumps(values, ensure_ascii=False)
