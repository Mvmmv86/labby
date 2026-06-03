# A3 Sales Inbox - Handoff

Data: 2026-06-02
Branch: `feature/f3-team-invites-modules`

## Escopo entregue

Fatia de Inbox/conversations do Sales, depois de Contacts.

Inclui:

- Migration `007_sales_inbox_foundation`.
- Models:
  - `SalesChannel`
  - `SalesContactChannel`
  - `SalesConversation`
  - `SalesMessage`
- Router `app/api/v2/labby/sales_conversations.py`.
- Service `app/domains/sales/conversation_service.py`.
- Schemas de conversa/mensagem/notificacao em `app/schemas/sales.py`.
- OpenAPI regenerado em `contracts/labby-openapi.yaml`.

## Rotas

Aliases flat usados pelo frontend atual:

- `GET /api/v2/labby/conversations/`
- `GET /api/v2/labby/conversations/notifications/summary`
- `GET /api/v2/labby/conversations/{conversation_id}`
- `PUT /api/v2/labby/conversations/{conversation_id}`
- `GET /api/v2/labby/conversations/{conversation_id}/messages`
- `POST /api/v2/labby/conversations/{conversation_id}/mark-read`
- `POST /api/v2/labby/conversations/{conversation_id}/messages`
- `POST /api/v2/labby/conversations/{conversation_id}/close`

Canonicamente tambem servidas em:

- `/api/v2/labby/sales/conversations/*`

## Decisoes

- IDs novos seguem UUID, consistente com `sales_contacts`.
- `assigned_to_membership_id` e `sender_membership_id` usam `membership_id`,
  nao `user_id`, para manter ator humano tenant-scoped.
- `send_message` persiste a mensagem de saida, atualiza conversa/contato e
  enfileira `sales.message.dispatch` quando a mensagem nasce `pending`.
  Evolution foi entregue na fatia de outbound; demais providers seguem
  pendentes.
- `auth/me` e respostas de auth agora retornam `canais_conectados` e `canais`
  calculados a partir de `sales_channels`, para a tela de Inbox habilitar quando
  houver canal conectado.

## Pontos anti-regressao

- Listagem de conversas usa CTEs para buscar ultima mensagem e nao-lidas em
  lote, sem subquery por linha no request path.
- Contacts passou a popular `total_conversas`, `canais_vinculados`, `canais` e
  `conversas_recentes` com agregacoes em lote.
- Mensagens externas tem unique parcial:
  `tenant_id + provider + external_id WHERE provider IS NOT NULL AND external_id IS NOT NULL`.
- Toda query de conversa/mensagem filtra `tenant_id`.
- Router exige `require_module("sales")`.

## Testes adicionados

- `tests/test_sales_conversation_routes.py`
  - contrato flat/canonico;
  - `require_module("sales")`;
  - payload de envio/update.
- `tests/test_sales_inbox_integration.py`
  - listagem Inbox com ultima mensagem e nao-lidas em Postgres real;
  - resumo de notificacoes;
  - agregacoes de Contacts a partir de conversas/canais;
  - cursor de mensagens;
  - `mark-read`;
  - envio interno atualizando counters;
  - `close`;
  - cross-tenant 404 com linha real em outro tenant;
  - dedupe por `provider + external_id`.

## Validacao local

- `ruff check .`
- `pytest -q` -> `91 passed, 2 skipped`
- `alembic upgrade head --sql`

Os testes de integracao Postgres rodam no CI quando `LABBY_TEST_DATABASE_URL`
esta configurado. Localmente ficam pulados se a env nao existir.

## Fora desta fatia

- CRUD completo de channels.
- Webhooks Evolution/Telegram/WhatsApp Cloud/Discord.
- Outbound real para WhatsApp Cloud/Telegram/Discord.
- Campaigns, bots, webchat/widget e analytics.
