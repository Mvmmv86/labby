import json
import re
from math import ceil
from typing import Any

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentMembership
from app.domains.identity.normalization import normalize_email


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d]", "", raw)
    if not cleaned:
        return None
    if cleaned.startswith("55") and len(cleaned) in (12, 13):
        return cleaned
    if len(cleaned) in (10, 11):
        return f"55{cleaned}"
    if len(cleaned) in (12, 13):
        return cleaned
    return cleaned


class SalesContactService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_contacts(
        self,
        *,
        current: CurrentMembership,
        search: str | None = None,
        grupo: str | None = None,
        tag: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        where_clauses = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(current.tenant_id)}

        if search:
            where_clauses.append(
                """
                (
                    name ILIKE :search
                    OR phone ILIKE :search
                    OR phone_normalized ILIKE :search
                    OR email_normalized ILIKE :search
                )
                """
            )
            params["search"] = f"%{search.strip()}%"

        if grupo:
            where_clauses.append("group_name = :group_name")
            params["group_name"] = grupo.strip()

        if tag:
            where_clauses.append("tags @> CAST(:tag AS jsonb)")
            params["tag"] = json.dumps([tag.strip()], ensure_ascii=False)

        where_sql = " AND ".join(where_clauses)
        total = self.db.execute(
            text(f"SELECT COUNT(*) FROM sales_contacts WHERE {where_sql}"),
            params,
        ).scalar_one()

        offset = (page - 1) * per_page
        params.update({"limit": per_page, "offset": offset})
        rows = (
            self.db.execute(
                text(
                    f"""
                    SELECT
                        id, name, phone, email_normalized, group_name, tags,
                        last_interaction_at, created_at
                    FROM sales_contacts
                    WHERE {where_sql}
                    ORDER BY last_interaction_at DESC NULLS LAST, created_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
        contact_ids = [row["id"] for row in rows]
        totals_by_contact, channels_by_contact = self._contact_conversation_summaries(
            tenant_id=str(current.tenant_id),
            contact_ids=contact_ids,
        )

        return {
            "contacts": [
                self._contact_list_row(
                    row,
                    total_conversations=totals_by_contact.get(str(row["id"]), 0),
                    linked_channels=channels_by_contact.get(str(row["id"]), []),
                )
                for row in rows
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, ceil(total / per_page)) if per_page else 1,
        }

    def get_contact(self, *, current: CurrentMembership, contact_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    SELECT *
                    FROM sales_contacts
                    WHERE id = :contact_id AND tenant_id = :tenant_id
                    """
                ),
                {"contact_id": contact_id, "tenant_id": str(current.tenant_id)},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Contato nao encontrado")
        totals_by_contact, channels_by_contact = self._contact_conversation_summaries(
            tenant_id=str(current.tenant_id),
            contact_ids=[str(row["id"])],
        )
        contact_id = str(row["id"])
        contact_uuid = row["id"]
        return self._contact_detail_row(
            row,
            total_conversations=totals_by_contact.get(contact_id, 0),
            linked_channels=channels_by_contact.get(contact_id, []),
            channels=self._contact_channels(
                tenant_id=str(current.tenant_id),
                contact_id=contact_uuid,
            ),
            recent_conversations=self._recent_conversations(
                tenant_id=str(current.tenant_id),
                contact_id=contact_uuid,
            ),
        )

    def create_contact(
        self,
        *,
        current: CurrentMembership,
        nome: str,
        telefone: str | None = None,
        email: str | None = None,
        grupo: str | None = None,
        tags: list[str] | None = None,
        notas: str | None = None,
        campos_custom: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        phone_normalized = normalize_phone(telefone)
        if phone_normalized:
            self._raise_if_phone_exists(current=current, phone_normalized=phone_normalized)

        try:
            row = (
                self.db.execute(
                    text(
                        """
                        INSERT INTO sales_contacts (
                            tenant_id, name, phone, phone_normalized, email_normalized,
                            group_name, tags, notes, custom_fields, created_by_membership_id,
                            updated_by_membership_id
                        )
                        VALUES (
                            :tenant_id, :name, :phone, :phone_normalized, :email_normalized,
                            :group_name, CAST(:tags AS jsonb), :notes,
                            CAST(:custom_fields AS jsonb), :membership_id, :membership_id
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "tenant_id": str(current.tenant_id),
                        "membership_id": str(current.membership_id),
                        "name": self._required_string(nome, "Nome e obrigatorio"),
                        "phone": self._optional_string(telefone),
                        "phone_normalized": phone_normalized,
                        "email_normalized": normalize_email(email) if email else None,
                        "group_name": self._optional_string(grupo),
                        "tags": self._json_array(self._clean_tags(tags)),
                        "notes": self._optional_string(notas),
                        "custom_fields": self._json_object(campos_custom or {}),
                    },
                )
                .mappings()
                .first()
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            self._raise_contact_integrity_error(exc)
        return self._mutation_row(row, message="Contato criado com sucesso")

    def update_contact(
        self,
        *,
        current: CurrentMembership,
        contact_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        updates = ["updated_by_membership_id = :membership_id", "updated_at = now()"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "membership_id": str(current.membership_id),
            "contact_id": contact_id,
        }

        if "nome" in patch:
            updates.append("name = :name")
            params["name"] = self._required_string(patch["nome"], "Nome nao pode ser vazio")

        if "telefone" in patch:
            phone_normalized = normalize_phone(patch["telefone"])
            if phone_normalized:
                self._raise_if_phone_exists(
                    current=current,
                    phone_normalized=phone_normalized,
                    exclude_contact_id=contact_id,
                )
            updates.extend(["phone = :phone", "phone_normalized = :phone_normalized"])
            params["phone"] = self._optional_string(patch["telefone"])
            params["phone_normalized"] = phone_normalized

        if "email" in patch:
            updates.append("email_normalized = :email_normalized")
            params["email_normalized"] = normalize_email(patch["email"]) if patch["email"] else None

        if "grupo" in patch:
            updates.append("group_name = :group_name")
            params["group_name"] = self._optional_string(patch["grupo"])

        if "tags" in patch:
            updates.append("tags = CAST(:tags AS jsonb)")
            params["tags"] = self._json_array(self._clean_tags(patch["tags"]))

        if "notas" in patch:
            updates.append("notes = :notes")
            params["notes"] = self._optional_string(patch["notas"])

        if "campos_custom" in patch:
            updates.append("custom_fields = CAST(:custom_fields AS jsonb)")
            params["custom_fields"] = self._json_object(patch["campos_custom"] or {})

        if "optout" in patch:
            updates.append("optout = :optout")
            params["optout"] = bool(patch["optout"])

        if "status" in patch:
            updates.append("status = :status")
            params["status"] = patch["status"]

        if len(updates) == 2:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        try:
            row = (
                self.db.execute(
                    text(
                        f"""
                        UPDATE sales_contacts
                        SET {", ".join(updates)}
                        WHERE id = :contact_id AND tenant_id = :tenant_id
                        RETURNING *
                        """
                    ),
                    params,
                )
                .mappings()
                .first()
            )
        except IntegrityError as exc:
            self.db.rollback()
            self._raise_contact_integrity_error(exc)
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Contato nao encontrado")
        self.db.commit()
        return self._mutation_row(row, message="Contato atualizado")

    def delete_contact(self, *, current: CurrentMembership, contact_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    DELETE FROM sales_contacts
                    WHERE id = :contact_id AND tenant_id = :tenant_id
                    RETURNING id
                    """
                ),
                {"contact_id": contact_id, "tenant_id": str(current.tenant_id)},
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Contato nao encontrado")
        self.db.commit()
        return {"id": row["id"], "message": "Contato removido"}

    def batch_import_contacts(
        self,
        *,
        current: CurrentMembership,
        contacts: list[dict[str, Any]],
        on_duplicate: str = "skip",
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_write_access(current)
        if len(contacts) > 1000:
            raise HTTPException(status_code=400, detail="Maximo de 1000 contatos por importacao")

        importados = 0
        duplicados = 0
        erros = 0
        sem_telefone = 0
        detalhes_erros: list[dict[str, Any]] = []

        for index, contact in enumerate(contacts, start=1):
            raw_phone = str(contact.get("telefone") or "").strip()
            phone_normalized = normalize_phone(raw_phone)
            if not phone_normalized:
                sem_telefone += 1
                erros += 1
                error_label = "Telefone vazio" if not raw_phone else "Telefone invalido"
                detalhes_erros.append({"linha": index, "telefone": raw_phone, "erro": error_label})
                continue

            name = str(contact.get("nome") or "").strip() or "Sem nome"
            email = str(contact.get("email") or "").strip() or None
            grupo = str(contact.get("grupo") or "").strip() or None
            notas = str(contact.get("notas") or "").strip() or None
            tags = self._clean_tags(contact.get("tags"))
            custom_fields = contact.get("campos_custom") if isinstance(contact, dict) else None
            custom_fields = custom_fields if isinstance(custom_fields, dict) else {}

            try:
                with self.db.begin_nested():
                    row = self._upsert_batch_contact(
                        current=current,
                        name=name,
                        phone=raw_phone,
                        phone_normalized=phone_normalized,
                        email=email,
                        grupo=grupo,
                        tags=tags,
                        notas=notas,
                        custom_fields=custom_fields,
                        on_duplicate=on_duplicate,
                    )
            except Exception as exc:
                erros += 1
                detalhes_erros.append(
                    {"linha": index, "telefone": raw_phone, "erro": str(exc)[:200]}
                )
                continue

            if row is None:
                duplicados += 1
            else:
                importados += 1

        self.db.commit()
        return {
            "total_enviados": len(contacts),
            "importados": importados,
            "duplicados": duplicados,
            "erros": erros,
            "sem_telefone": sem_telefone,
            "detalhes_erros": detalhes_erros[:50],
        }

    def _assert_sales_access(self, current: CurrentMembership) -> None:
        if current.role == "owner":
            return
        if "sales" not in current.modules:
            raise HTTPException(status_code=403, detail="Modulo sales nao habilitado")

    @staticmethod
    def _assert_write_access(current: CurrentMembership) -> None:
        if current.role not in {"owner", "admin", "agent"}:
            raise HTTPException(status_code=403, detail="Permissao insuficiente")

    def _raise_if_phone_exists(
        self,
        *,
        current: CurrentMembership,
        phone_normalized: str,
        exclude_contact_id: str | None = None,
    ) -> None:
        row = self._find_by_phone(current=current, phone_normalized=phone_normalized)
        if row and str(row["id"]) != str(exclude_contact_id):
            raise HTTPException(status_code=409, detail="Ja existe um contato com esse telefone")

    def _find_by_phone(self, *, current: CurrentMembership, phone_normalized: str):
        return (
            self.db.execute(
                text(
                    """
                    SELECT id
                    FROM sales_contacts
                    WHERE tenant_id = :tenant_id AND phone_normalized = :phone_normalized
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "phone_normalized": phone_normalized,
                },
            )
            .mappings()
            .first()
        )

    def _upsert_batch_contact(
        self,
        *,
        current: CurrentMembership,
        name: str,
        phone: str,
        phone_normalized: str,
        email: str | None,
        grupo: str | None,
        tags: list[str],
        notas: str | None,
        custom_fields: dict[str, Any],
        on_duplicate: str,
    ):
        params = {
            "tenant_id": str(current.tenant_id),
            "membership_id": str(current.membership_id),
            "name": name,
            "phone": phone,
            "phone_normalized": phone_normalized,
            "email_normalized": normalize_email(email) if email else None,
            "group_name": grupo,
            "tags": self._json_array(tags),
            "notes": notas,
            "custom_fields": self._json_object(custom_fields),
        }
        if on_duplicate == "update":
            statement = """
                INSERT INTO sales_contacts (
                    tenant_id, name, phone, phone_normalized, email_normalized,
                    group_name, tags, notes, custom_fields, created_by_membership_id,
                    updated_by_membership_id
                )
                VALUES (
                    :tenant_id, :name, :phone, :phone_normalized, :email_normalized,
                    :group_name, CAST(:tags AS jsonb), :notes, CAST(:custom_fields AS jsonb),
                    :membership_id, :membership_id
                )
                ON CONFLICT (tenant_id, phone_normalized)
                    WHERE phone_normalized IS NOT NULL
                DO UPDATE SET
                    name = EXCLUDED.name,
                    phone = EXCLUDED.phone,
                    email_normalized = EXCLUDED.email_normalized,
                    group_name = EXCLUDED.group_name,
                    tags = EXCLUDED.tags,
                    notes = EXCLUDED.notes,
                    custom_fields = sales_contacts.custom_fields || EXCLUDED.custom_fields,
                    updated_by_membership_id = EXCLUDED.updated_by_membership_id,
                    updated_at = now()
                RETURNING (xmax = 0) AS inserted
            """
        else:
            statement = """
                INSERT INTO sales_contacts (
                    tenant_id, name, phone, phone_normalized, email_normalized,
                    group_name, tags, notes, custom_fields, created_by_membership_id,
                    updated_by_membership_id
                )
                VALUES (
                    :tenant_id, :name, :phone, :phone_normalized, :email_normalized,
                    :group_name, CAST(:tags AS jsonb), :notes, CAST(:custom_fields AS jsonb),
                    :membership_id, :membership_id
                )
                ON CONFLICT (tenant_id, phone_normalized)
                    WHERE phone_normalized IS NOT NULL
                DO NOTHING
                RETURNING true AS inserted
            """
        return self.db.execute(text(statement), params).mappings().first()

    @staticmethod
    def _raise_contact_integrity_error(exc: IntegrityError) -> None:
        constraint_name = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint_name, "constraint_name", "") or str(exc.orig)
        if "uq_sales_contacts_tenant_phone_normalized" in constraint_name:
            raise HTTPException(status_code=409, detail="Ja existe um contato com esse telefone")
        raise HTTPException(status_code=409, detail="Conflito ao salvar contato")

    def _contact_conversation_summaries(
        self,
        *,
        tenant_id: str,
        contact_ids: list[Any],
    ) -> tuple[dict[str, int], dict[str, list[str]]]:
        if not contact_ids:
            return {}, {}

        conversation_rows = (
            self.db.execute(
                text(
                    """
                    SELECT
                        c.contact_id,
                        COUNT(*) AS total_conversations,
                        COALESCE(
                            array_agg(DISTINCT ch.channel_type)
                                FILTER (WHERE ch.channel_type IS NOT NULL),
                            '{}'
                        ) AS conversation_channels
                    FROM sales_conversations c
                    LEFT JOIN sales_channels ch
                      ON ch.id = c.channel_id
                     AND ch.tenant_id = c.tenant_id
                    WHERE c.tenant_id = :tenant_id
                      AND c.contact_id IN :contact_ids
                    GROUP BY c.contact_id
                    """
                ).bindparams(bindparam("contact_ids", expanding=True)),
                {"tenant_id": tenant_id, "contact_ids": contact_ids},
            )
            .mappings()
            .all()
        )
        channel_rows = (
            self.db.execute(
                text(
                    """
                    SELECT
                        contact_id,
                        COALESCE(array_agg(DISTINCT channel_type), '{}') AS contact_channels
                    FROM sales_contact_channels
                    WHERE tenant_id = :tenant_id
                      AND contact_id IN :contact_ids
                    GROUP BY contact_id
                    """
                ).bindparams(bindparam("contact_ids", expanding=True)),
                {"tenant_id": tenant_id, "contact_ids": contact_ids},
            )
            .mappings()
            .all()
        )

        totals_by_contact = {
            str(row["contact_id"]): int(row["total_conversations"] or 0)
            for row in conversation_rows
        }
        channels_by_contact: dict[str, list[str]] = {}
        for row in conversation_rows:
            contact_id = str(row["contact_id"])
            channels_by_contact.setdefault(contact_id, [])
            channels_by_contact[contact_id].extend(row["conversation_channels"] or [])
        for row in channel_rows:
            contact_id = str(row["contact_id"])
            channels_by_contact.setdefault(contact_id, [])
            channels_by_contact[contact_id].extend(row["contact_channels"] or [])

        for contact_id, channels in channels_by_contact.items():
            seen: set[str] = set()
            deduped_channels: list[str] = []
            for channel in channels:
                if channel and channel not in seen:
                    deduped_channels.append(channel)
                    seen.add(channel)
            channels_by_contact[contact_id] = deduped_channels
        return totals_by_contact, channels_by_contact

    def _contact_channels(self, *, tenant_id: str, contact_id: Any) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                text(
                    """
                    SELECT channel_type, identifier, created_at
                    FROM sales_contact_channels
                    WHERE tenant_id = :tenant_id
                      AND contact_id = :contact_id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"tenant_id": tenant_id, "contact_id": contact_id},
            )
            .mappings()
            .all()
        )
        return [
            {
                "tipo_canal": row["channel_type"],
                "identificador": row["identifier"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _recent_conversations(self, *, tenant_id: str, contact_id: Any) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                text(
                    """
                    WITH recent AS (
                        SELECT
                            c.id,
                            c.status,
                            c.subject,
                            c.assigned_to_membership_id,
                            c.last_message_at,
                            c.created_at,
                            ch.channel_type,
                            ch.name AS channel_name,
                            u.nome AS assigned_name
                        FROM sales_conversations c
                        LEFT JOIN sales_channels ch
                          ON ch.id = c.channel_id
                         AND ch.tenant_id = c.tenant_id
                        LEFT JOIN memberships am
                          ON am.id = c.assigned_to_membership_id
                         AND am.tenant_id = c.tenant_id
                        LEFT JOIN users u ON u.id = am.user_id
                        WHERE c.tenant_id = :tenant_id
                          AND c.contact_id = :contact_id
                        ORDER BY
                            c.last_message_at DESC NULLS LAST,
                            c.created_at DESC,
                            c.id DESC
                        LIMIT 5
                    ),
                    last_messages AS (
                        SELECT DISTINCT ON (m.conversation_id)
                            m.conversation_id,
                            m.content,
                            m.created_at
                        FROM sales_messages m
                        JOIN recent r ON r.id = m.conversation_id
                        WHERE m.tenant_id = :tenant_id
                        ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
                    )
                    SELECT
                        r.*,
                        lm.content AS last_message,
                        COALESCE(lm.created_at, r.last_message_at) AS effective_last_message_at
                    FROM recent r
                    LEFT JOIN last_messages lm ON lm.conversation_id = r.id
                    ORDER BY
                        r.last_message_at DESC NULLS LAST,
                        r.created_at DESC,
                        r.id DESC
                    """
                ),
                {"tenant_id": tenant_id, "contact_id": contact_id},
            )
            .mappings()
            .all()
        )
        return [
            {
                "id": row["id"],
                "channel_tipo": row["channel_type"],
                "channel_nome": row["channel_name"],
                "status": row["status"],
                "assunto": row["subject"],
                "atendente_nome": row["assigned_name"],
                "ultima_mensagem": row["last_message"],
                "ultima_mensagem_at": row["effective_last_message_at"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _contact_list_row(
        row,
        *,
        total_conversations: int = 0,
        linked_channels: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": row["id"],
            "nome": row["name"] or "Sem nome",
            "telefone": row["phone"],
            "email": row["email_normalized"],
            "tags": row["tags"] or [],
            "grupo": row["group_name"],
            "total_conversas": total_conversations,
            "canais_vinculados": linked_channels or [],
            "ultima_interacao": row["last_interaction_at"],
            "created_at": row["created_at"],
        }

    @classmethod
    def _contact_detail_row(
        cls,
        row,
        *,
        total_conversations: int = 0,
        linked_channels: list[str] | None = None,
        channels: list[dict[str, Any]] | None = None,
        recent_conversations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        data = cls._contact_list_row(
            row,
            total_conversations=total_conversations,
            linked_channels=linked_channels or [],
        )
        data.update(
            {
                "notas": row["notes"],
                "campos_custom": row["custom_fields"] or {},
                "total_mensagens_enviadas": row["total_messages_sent"] or 0,
                "total_mensagens_recebidas": row["total_messages_received"] or 0,
                "optout": row["optout"] or False,
                "status": row["status"],
                "updated_at": row["updated_at"],
                "canais": channels or [],
                "conversas_recentes": recent_conversations or [],
            }
        )
        return data

    @staticmethod
    def _mutation_row(row, *, message: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "nome": row["name"],
            "telefone": row["phone"],
            "email": row["email_normalized"],
            "grupo": row["group_name"],
            "tags": row["tags"] or [],
            "notas": row["notes"],
            "campos_custom": row["custom_fields"] or {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message": message,
        }

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
    def _json_array(values: list[str]) -> str:
        return json.dumps(values, ensure_ascii=False)

    @staticmethod
    def _json_object(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)
