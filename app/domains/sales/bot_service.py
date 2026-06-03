import json
from math import ceil
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentMembership

TRIAL_BOT_LIMIT = 1
DEFAULT_BOT_LIMIT = 10
HUMAN_HANDOFF_WORDS = {
    "atendente",
    "humano",
    "pessoa",
    "suporte",
    "vendedor",
    "consultor",
}


class SalesBotService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_bots(
        self,
        *,
        current: CurrentMembership,
        search: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(current.tenant_id)}
        if search:
            where.append("name ILIKE :search")
            params["search"] = f"%{search.strip()}%"
        where_sql = " AND ".join(where)
        total = self.db.execute(
            text(f"SELECT COUNT(*) FROM sales_bots WHERE {where_sql}"),
            params,
        ).scalar_one()
        params.update({"limit": per_page, "offset": (page - 1) * per_page})
        rows = (
            self.db.execute(
                text(
                    f"""
                    SELECT *
                    FROM sales_bots
                    WHERE {where_sql}
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
        return {
            "bots": [self._bot_list_row(row) for row in rows],
            "total": int(total or 0),
            "page": page,
            "per_page": per_page,
            "pages": max(1, ceil(int(total or 0) / per_page)) if per_page else 1,
        }

    def get_bot(self, *, current: CurrentMembership, bot_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        row = self._bot_row(tenant_id=str(current.tenant_id), bot_id=bot_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Bot nao encontrado")
        return self._bot_detail_row(row)

    def create_bot(
        self,
        *,
        current: CurrentMembership,
        nome: str,
        descricao: str | None = None,
        system_prompt: str | None = None,
        welcome_message: str | None = None,
        fallback_message: str | None = None,
        base_conhecimento: str | None = None,
        faqs: list[dict[str, Any]] | None = None,
        modelo: str = "gpt-4o-mini",
        temperatura: float = 0.3,
        max_tokens: int = 800,
        tipo_trigger: str = "todas_mensagens",
        trigger_valor: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        self._assert_bot_limit(str(current.tenant_id))
        validated_channel_ids = self._validate_channel_ids(
            tenant_id=str(current.tenant_id),
            channel_ids=channel_ids or [],
        )
        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_bots (
                        tenant_id, name, description, system_prompt, welcome_message,
                        fallback_message, knowledge_base, faqs, model, temperature,
                        max_tokens, trigger_type, trigger_value, channel_ids,
                        created_by_membership_id, updated_by_membership_id
                    )
                    VALUES (
                        :tenant_id, :name, :description, :system_prompt, :welcome_message,
                        :fallback_message, :knowledge_base, CAST(:faqs AS jsonb),
                        :model, :temperature, :max_tokens, :trigger_type,
                        :trigger_value, CAST(:channel_ids AS jsonb),
                        :membership_id, :membership_id
                    )
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "membership_id": str(current.membership_id),
                    "name": self._required_string(nome, "Nome do bot e obrigatorio"),
                    "description": self._optional_string(descricao),
                    "system_prompt": self._optional_string(system_prompt),
                    "welcome_message": self._optional_string(welcome_message),
                    "fallback_message": self._optional_string(fallback_message),
                    "knowledge_base": self._optional_string(base_conhecimento),
                    "faqs": self._json_array(faqs or []),
                    "model": self._optional_string(modelo) or "gpt-4o-mini",
                    "temperature": temperatura,
                    "max_tokens": max_tokens,
                    "trigger_type": tipo_trigger,
                    "trigger_value": self._optional_string(trigger_valor),
                    "channel_ids": self._json_array(validated_channel_ids),
                },
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return self._bot_detail_row(row)

    def update_bot(
        self,
        *,
        current: CurrentMembership,
        bot_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        updates = ["updated_by_membership_id = :membership_id", "updated_at = NOW()"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "membership_id": str(current.membership_id),
            "bot_id": UUID(str(bot_id)),
        }
        field_map = {
            "nome": ("name", lambda value: self._required_string(value, "Nome nao pode ser vazio")),
            "descricao": ("description", self._optional_string),
            "system_prompt": ("system_prompt", self._optional_string),
            "welcome_message": ("welcome_message", self._optional_string),
            "fallback_message": ("fallback_message", self._optional_string),
            "base_conhecimento": ("knowledge_base", self._optional_string),
            "modelo": ("model", lambda value: self._optional_string(value) or "gpt-4o-mini"),
            "temperatura": ("temperature", lambda value: value),
            "max_tokens": ("max_tokens", lambda value: value),
            "tipo_trigger": ("trigger_type", lambda value: value),
            "trigger_valor": ("trigger_value", self._optional_string),
            "ativo": ("active", lambda value: value),
        }
        for key, (column, transform) in field_map.items():
            if key in patch:
                updates.append(f"{column} = :{column}")
                params[column] = transform(patch[key])

        if "faqs" in patch:
            updates.append("faqs = CAST(:faqs AS jsonb)")
            params["faqs"] = self._json_array(patch["faqs"] or [])

        if "channel_ids" in patch:
            updates.append("channel_ids = CAST(:channel_ids AS jsonb)")
            params["channel_ids"] = self._json_array(
                self._validate_channel_ids(
                    tenant_id=str(current.tenant_id),
                    channel_ids=[str(channel_id) for channel_id in patch["channel_ids"] or []],
                )
            )

        if len(updates) == 2:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        row = (
            self.db.execute(
                text(
                    f"""
                    UPDATE sales_bots
                    SET {", ".join(updates)}
                    WHERE tenant_id = :tenant_id
                      AND id = :bot_id
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
            raise HTTPException(status_code=404, detail="Bot nao encontrado")
        self.db.commit()
        return self._bot_detail_row(row)

    def delete_bot(self, *, current: CurrentMembership, bot_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    DELETE FROM sales_bots
                    WHERE tenant_id = :tenant_id
                      AND id = :bot_id
                      AND active = false
                    RETURNING id
                    """
                ),
                {"tenant_id": str(current.tenant_id), "bot_id": UUID(str(bot_id))},
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(
                status_code=404,
                detail="Bot nao encontrado ou ainda ativo",
            )
        self.db.commit()
        return {"id": row["id"], "message": "Bot removido com sucesso"}

    def toggle_bot(self, *, current: CurrentMembership, bot_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    UPDATE sales_bots
                    SET active = NOT active,
                        updated_by_membership_id = :membership_id,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :bot_id
                    RETURNING id, name, active
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "membership_id": str(current.membership_id),
                    "bot_id": UUID(str(bot_id)),
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Bot nao encontrado")
        self.db.commit()
        return {
            "id": row["id"],
            "nome": row["name"],
            "ativo": bool(row["active"]),
            "message": f"Bot {'ativado' if row['active'] else 'desativado'}",
        }

    def duplicate_bot(self, *, current: CurrentMembership, bot_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        self._assert_bot_limit(str(current.tenant_id))
        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_bots (
                        tenant_id, name, description, system_prompt, welcome_message,
                        fallback_message, knowledge_base, faqs, model, temperature,
                        max_tokens, trigger_type, trigger_value, channel_ids,
                        active, created_by_membership_id, updated_by_membership_id
                    )
                    SELECT
                        tenant_id, name || ' (copia)', description, system_prompt,
                        welcome_message, fallback_message, knowledge_base, faqs,
                        model, temperature, max_tokens, trigger_type, trigger_value,
                        channel_ids, false, :membership_id, :membership_id
                    FROM sales_bots
                    WHERE tenant_id = :tenant_id
                      AND id = :bot_id
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "membership_id": str(current.membership_id),
                    "bot_id": UUID(str(bot_id)),
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Bot nao encontrado")
        self.db.commit()
        return self._bot_detail_row(row)

    def maybe_respond_to_widget_message(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        conversation_id: str,
        contact_id: str,
        input_message_id: str,
        message_text: str,
        widget_id: str,
    ) -> str | None:
        conversation = (
            self.db.execute(
                text(
                    """
                    SELECT id, bot_active, bot_id
                    FROM sales_conversations
                    WHERE tenant_id = :tenant_id
                      AND id = :conversation_id
                    FOR UPDATE
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": UUID(str(conversation_id)),
                },
            )
            .mappings()
            .first()
        )
        if conversation is None:
            return None
        if conversation["bot_active"] is False and conversation["bot_id"] is not None:
            return None

        bot = self._active_bot_for_channel(
            tenant_id=tenant_id,
            channel_id=channel_id,
            conversation=conversation,
            message_text=message_text,
        )
        if bot is None:
            return None

        response_text, transferred = self._build_widget_response(bot, message_text)
        if not response_text:
            self._record_bot_run(
                tenant_id=tenant_id,
                bot_id=str(bot["id"]),
                conversation_id=conversation_id,
                input_message_id=input_message_id,
                output_message_id=None,
                status="skipped",
                input_text=message_text,
                output_text=None,
                metadata={"reason": "no_response"},
            )
            return None

        self.db.execute(
            text(
                """
                UPDATE sales_bots
                SET total_triggers = total_triggers + 1,
                    total_completed = total_completed + :completed_increment,
                    total_transferred = total_transferred + :transferred_increment,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :bot_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "bot_id": bot["id"],
                "completed_increment": 0 if transferred else 1,
                "transferred_increment": 1 if transferred else 0,
            },
        )
        output = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_messages (
                        tenant_id, conversation_id, contact_id, direction,
                        sender_type, message_type, content, provider, external_id,
                        status, metadata
                    )
                    VALUES (
                        :tenant_id, :conversation_id, :contact_id, 'saida',
                        'bot', 'text', :content, 'web_widget', :external_id,
                        'sent', CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (tenant_id, provider, external_id)
                        WHERE provider IS NOT NULL AND external_id IS NOT NULL
                    DO NOTHING
                    RETURNING id, created_at
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": UUID(str(conversation_id)),
                    "contact_id": UUID(str(contact_id)),
                    "content": response_text,
                    "external_id": f"widget:{widget_id}:bot:{input_message_id}",
                    "metadata": self._json_object({"bot_id": str(bot["id"])}),
                },
            )
            .mappings()
            .first()
        )
        output_message_id = output["id"] if output is not None else None
        if output is not None:
            self.db.execute(
                text(
                    """
                    UPDATE sales_conversations
                    SET bot_active = :bot_active,
                        bot_id = :bot_id,
                        waiting_for_human = :waiting_for_human,
                        last_message_at = :last_message_at,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :conversation_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": UUID(str(conversation_id)),
                    "bot_active": not transferred,
                    "bot_id": bot["id"],
                    "waiting_for_human": transferred,
                    "last_message_at": output["created_at"],
                },
            )
            self.db.execute(
                text(
                    """
                    UPDATE sales_contacts
                    SET total_messages_sent = total_messages_sent + 1,
                        last_interaction_at = :last_message_at,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :contact_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": UUID(str(contact_id)),
                    "last_message_at": output["created_at"],
                },
            )

        self._record_bot_run(
            tenant_id=tenant_id,
            bot_id=str(bot["id"]),
            conversation_id=conversation_id,
            input_message_id=input_message_id,
            output_message_id=str(output_message_id) if output_message_id else None,
            status="succeeded",
            input_text=message_text,
            output_text=response_text,
            metadata={"transferred": transferred},
        )
        return response_text

    def _active_bot_for_channel(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        conversation,
        message_text: str,
    ):
        rows = (
            self.db.execute(
                text(
                    """
                    SELECT *
                    FROM sales_bots
                    WHERE tenant_id = :tenant_id
                      AND active = true
                      AND channel_ids @> CAST(:channel_ids AS jsonb)
                    ORDER BY created_at ASC, id ASC
                    LIMIT 10
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "channel_ids": self._json_array([str(UUID(str(channel_id)))]),
                },
            )
            .mappings()
            .all()
        )
        for bot in rows:
            if self._trigger_matches(bot, conversation=conversation, message_text=message_text):
                return bot
        return None

    def _trigger_matches(self, bot, *, conversation, message_text: str) -> bool:
        trigger_type = bot["trigger_type"] or "todas_mensagens"
        if trigger_type == "todas_mensagens":
            return True
        if trigger_type == "primeira_mensagem":
            return conversation["bot_id"] is None
        if trigger_type == "keyword":
            keyword = str(bot["trigger_value"] or "").strip().casefold()
            return bool(keyword and keyword in message_text.casefold())
        return False

    def _build_widget_response(self, bot, message_text: str) -> tuple[str | None, bool]:
        normalized_message = message_text.casefold()
        if any(word in normalized_message for word in HUMAN_HANDOFF_WORDS):
            return (
                bot["fallback_message"] or "Vou transferir voce para um atendente humano.",
                True,
            )

        for faq in bot["faqs"] or []:
            if not isinstance(faq, dict):
                continue
            question = str(faq.get("pergunta") or faq.get("question") or "").strip()
            answer = str(faq.get("resposta") or faq.get("answer") or "").strip()
            if question and answer and question.casefold() in normalized_message:
                return answer, False

        if bot["trigger_type"] == "primeira_mensagem" and bot["welcome_message"]:
            return bot["welcome_message"], False

        if bot["fallback_message"]:
            return bot["fallback_message"], False

        return None, False

    def _record_bot_run(
        self,
        *,
        tenant_id: str,
        bot_id: str,
        conversation_id: str,
        input_message_id: str,
        output_message_id: str | None,
        status: str,
        input_text: str,
        output_text: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO sales_bot_runs (
                    tenant_id, bot_id, conversation_id, input_message_id,
                    output_message_id, status, input_text, output_text, metadata,
                    finished_at
                )
                VALUES (
                    :tenant_id, :bot_id, :conversation_id, :input_message_id,
                    :output_message_id, :status, :input_text, :output_text,
                    CAST(:metadata AS jsonb), NOW()
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "bot_id": UUID(str(bot_id)),
                "conversation_id": UUID(str(conversation_id)),
                "input_message_id": UUID(str(input_message_id)),
                "output_message_id": UUID(str(output_message_id)) if output_message_id else None,
                "status": status,
                "input_text": input_text,
                "output_text": output_text,
                "metadata": self._json_object(metadata),
            },
        )

    def _bot_row(self, *, tenant_id: str, bot_id: str):
        return (
            self.db.execute(
                text(
                    """
                    SELECT *
                    FROM sales_bots
                    WHERE tenant_id = :tenant_id
                      AND id = :bot_id
                    """
                ),
                {"tenant_id": tenant_id, "bot_id": UUID(str(bot_id))},
            )
            .mappings()
            .first()
        )

    def _validate_channel_ids(self, *, tenant_id: str, channel_ids: list[str]) -> list[str]:
        unique_ids = [str(UUID(str(channel_id))) for channel_id in dict.fromkeys(channel_ids)]
        if not unique_ids:
            return []
        valid = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sales_channels
                WHERE tenant_id = :tenant_id
                  AND id = ANY(CAST(:channel_ids AS uuid[]))
                """
            ),
            {"tenant_id": tenant_id, "channel_ids": unique_ids},
        ).scalar_one()
        if int(valid or 0) != len(unique_ids):
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        return unique_ids

    def _assert_bot_limit(self, tenant_id: str) -> None:
        row = self.db.execute(
            text(
                """
                SELECT plano
                FROM tenants
                WHERE id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first()
        plan = str(row["plano"] if row else "trial").lower()
        limit = TRIAL_BOT_LIMIT if plan == "trial" else DEFAULT_BOT_LIMIT
        current_count = self.db.execute(
            text("SELECT COUNT(*) FROM sales_bots WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
        if int(current_count or 0) >= limit:
            raise HTTPException(
                status_code=403,
                detail=f"Limite de {limit} bot(s) atingido. Faca upgrade do plano.",
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
    def _bot_list_row(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "nome": row["name"],
            "descricao": row["description"],
            "modelo": row["model"] or "gpt-4o-mini",
            "tipo_trigger": row["trigger_type"] or "todas_mensagens",
            "ativo": bool(row["active"]),
            "total_acionamentos": int(row["total_triggers"] or 0),
            "total_concluidos": int(row["total_completed"] or 0),
            "total_transferidos": int(row["total_transferred"] or 0),
            "channel_ids": [UUID(str(channel_id)) for channel_id in row["channel_ids"] or []],
            "created_at": row["created_at"],
        }

    @classmethod
    def _bot_detail_row(cls, row) -> dict[str, Any]:
        data = cls._bot_list_row(row)
        data.update(
            {
                "system_prompt": row["system_prompt"],
                "welcome_message": row["welcome_message"],
                "fallback_message": row["fallback_message"],
                "base_conhecimento": row["knowledge_base"],
                "faqs": row["faqs"] or [],
                "temperatura": float(row["temperature"] or 0.3),
                "max_tokens": int(row["max_tokens"] or 800),
                "trigger_valor": row["trigger_value"],
                "criado_por": row["created_by_membership_id"],
                "updated_at": row["updated_at"],
            }
        )
        return data

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

    @staticmethod
    def _json_array(values: list[Any]) -> str:
        return json.dumps(values, ensure_ascii=False, default=str)

    @staticmethod
    def _json_object(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)
