# A3 - Sales Contacts: handoff tecnico

Data: 2026-06-01

## Entregue

- Migration `006_sales_contacts_foundation`.
- Tabela `sales_contacts`.
- Modelo SQLAlchemy `SalesContact`.
- `SalesContactService` tenant-scoped.
- Endpoints flat compativeis com o frontend atual:
  - `GET /api/v2/labby/contacts/`
  - `GET /api/v2/labby/contacts/{contact_id}`
  - `POST /api/v2/labby/contacts/`
  - `PUT /api/v2/labby/contacts/{contact_id}`
  - `DELETE /api/v2/labby/contacts/{contact_id}`
  - `POST /api/v2/labby/contacts/batch`
- Endpoints canonicos novos:
  - `GET /api/v2/labby/sales/contacts/`
  - `GET /api/v2/labby/sales/contacts/{contact_id}`
  - `POST /api/v2/labby/sales/contacts/`
  - `PUT /api/v2/labby/sales/contacts/{contact_id}`
  - `DELETE /api/v2/labby/sales/contacts/{contact_id}`
  - `POST /api/v2/labby/sales/contacts/batch`
- `require_module("sales")` aplicado no router.
- Mutations bloqueadas para role `viewer`.
- Actor humano salvo por `created_by_membership_id` e `updated_by_membership_id`.
- Listagem paginada com filtros `search`, `grupo` e `tag`.
- Normalizacao de telefone com DDI `55` quando aplicavel.
- Normalizacao de email por `normalize_email`.
- Unique parcial por `tenant_id + phone_normalized` quando telefone existe.
- Batch import idempotente por telefone normalizado dentro do tenant.
- Respostas mantem campos esperados pelo frontend legado:
  - `nome`
  - `telefone`
  - `email`
  - `grupo`
  - `tags`
  - `notas`
  - `campos_custom`
  - `total_conversas`
  - `canais_vinculados`
  - `conversas_recentes`

## Escopo propositalmente fora desta fatia

- Inbox/conversations.
- Canais vinculados reais.
- Webhooks de Evolution, WhatsApp Cloud, Telegram e Discord.
- Campanhas, bots e webchat.
- Audit log dedicado para acoes criticas de Sales.

Os campos de conversas/canais voltam vazios ou zerados ate a fatia de Inbox.
Isso preserva contrato sem fingir integracao ainda inexistente.

## Invariantes

- Toda query filtra por `tenant_id`.
- Nenhum contato de outro tenant deve ser lido, alterado ou removido.
- Um contato com telefone normalizado duplicado no mesmo tenant nao pode ser
  criado duas vezes.
- Batch import com `on_duplicate=skip` nao duplica contato.
- Batch import com `on_duplicate=update` atualiza o contato existente.
- Nenhuma rota de Contacts deve funcionar sem modulo `sales`.

## Validacao local

- `ruff check .`
- `pytest -q`
- `alembic upgrade head --sql`
- OpenAPI regenerado em `contracts/labby-openapi.yaml`.

## Proxima fatia

1. Review adversarial de A3 Contacts.
2. Smoke de CRUD/listagem/batch no frontend Sales.
3. A3 Inbox/conversations com o primeiro canal/webhook via `webhook_events` e
   jobs.
