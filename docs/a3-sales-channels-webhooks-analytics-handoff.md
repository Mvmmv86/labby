# A3 Sales Channels, Webhooks e Analytics - Handoff

Data: 2026-06-02
Branch: `feature/f3-team-invites-modules`

## Escopo entregue

Fatia de Sales depois de Contacts e Inbox.

Inclui:

- CRUD de canais em `app/domains/sales/channel_service.py`.
- Router `app/api/v2/labby/sales_channels.py`.
- Webhook publico Evolution em `app/api/v2/labby/sales_webhooks.py`.
- Receiver de webhook em `app/domains/sales/webhook_service.py`.
- Handler de job `sales.webhook.evolution` em
  `app/domains/sales/webhook_jobs.py`.
- Analytics do dashboard em `app/domains/sales/analytics_service.py`.
- Router `app/api/v2/labby/sales_analytics.py`.
- Integracao standalone de canais em `app/integrations/sales_channels.py`.
- Settings `LABBY_PUBLIC_API_BASE_URL`, `LABBY_EVOLUTION_API_URL`,
  `LABBY_EVOLUTION_API_KEY` e `LABBY_EVOLUTION_API_TIMEOUT_SECONDS`.

## Rotas

Channels flat e canonico:

- `GET /api/v2/labby/channels/`
- `POST /api/v2/labby/channels/`
- `GET /api/v2/labby/channels/{channel_id}`
- `PUT /api/v2/labby/channels/{channel_id}`
- `DELETE /api/v2/labby/channels/{channel_id}`
- `GET /api/v2/labby/channels/{channel_id}/status`
- `POST /api/v2/labby/channels/{channel_id}/connect`
- `POST /api/v2/labby/channels/{channel_id}/disconnect`
- mesmas rotas em `/api/v2/labby/sales/channels/*`

Webhook publico:

- `POST /api/v2/labby/webhooks/evolution/{channel_id}`

Analytics flat e canonico:

- `GET /api/v2/labby/analytics/dashboard`
- `GET /api/v2/labby/analytics/messages`
- `GET /api/v2/labby/analytics/activity`
- mesmas rotas em `/api/v2/labby/sales/analytics/*`

## Decisoes

- Respostas de channels redigem campos sensiveis de `config` e nunca expõem
  `webhook_secret`.
- Mutations de channels exigem owner/admin, alem do modulo `sales`.
- Connect de Evolution tenta usar `LABBY_EVOLUTION_API_*` quando configurado e
  aponta o webhook para `LABBY_PUBLIC_API_BASE_URL`.
- Sem `LABBY_EVOLUTION_API_*`, o canal fica em `conectando` e retorna mensagem
  clara de provider nao configurado.
- Web Chat gera `widget_id` e snippet publico a partir de
  `LABBY_PUBLIC_API_BASE_URL`.
- Connect real fica habilitado somente para Evolution e Web Chatbot nesta
  fatia. Telegram, Discord e WhatsApp Cloud podem ser cadastrados, mas o
  connect retorna `501` ate seus receivers inbound existirem.
- O webhook Evolution valida segredo por comparacao constante e aceita os
  headers `X-Labby-Webhook-Secret`, `X-OmniaFlow-Webhook-Secret` e
  `X-Evolution-Token`.
- Evento bruto e job sao gravados na mesma transacao usando
  `webhook_events` + `jobs`.
- Eventos Evolution que criariam ou atualizariam mensagens so viram job quando
  o canal esta `conectado`. Se o canal esta desconectado, o evento bruto e
  persistido como `ignored` e nenhum job e criado.
- Handler do job cria/atualiza contato, vinculo de canal, conversa e mensagem,
  com dedupe por `tenant_id + provider + external_id`.
- Webhook `messages.update` reconcilia status de mensagens enviadas por
  `delivery_provider + delivery_external_id`.
- Webhook publico Evolution tem rate limit auditavel por canal apos validar
  secret. Nao ha gargalo por IP, porque o provider pode entregar todo o
  trafego legitimo por uma unica origem.
- Analytics usa apenas tabelas ja existentes. `campanhas_ativas` fica `0` ate
  a migration de campanhas entrar.

## Pontos anti-regressao

- Reenvio do mesmo webhook nao duplica `webhook_events`, `jobs` ou
  `sales_messages`.
- Reprocessamento de job ja processado retorna `skipped`.
- Contadores de contato so sao incrementados quando a mensagem externa e
  inserida de fato.
- Webhook invalido por secret errado retorna `401`.
- Webhook de mensagem em canal desconectado nao cria job nem mensagem.
- Connect de Telegram, Discord e WhatsApp Cloud fica bloqueado ate haver rota
  inbound correspondente.
- Channels tem aliases flat porque campanhas e bots ainda usam `/channels/`.

## Testes adicionados

- `tests/test_sales_channel_routes.py`
  - contrato flat/canonico;
  - `require_module("sales")`;
  - connect/disconnect/status.
- `tests/test_sales_webhook_routes.py`
  - endpoint publico Evolution enfileira evento.
- `tests/test_sales_webhooks_integration.py`
  - handler registrado;
  - redacao de config sensivel;
  - webhook Evolution em Postgres real;
  - duplicate webhook sem duplicar mensagem;
  - mensagem Evolution ignorada quando canal esta desconectado;
  - connect externo bloqueado para provider sem inbound;
  - segredo errado rejeitado.
- `tests/test_sales_analytics_routes.py`
  - contrato flat/canonico do dashboard, volume e activity.

## Validacao local

- `ruff check .`
- `pytest -q` -> `98 passed, 3 skipped`

Os testes de integracao Postgres rodam no CI quando `LABBY_TEST_DATABASE_URL`
esta configurado. Localmente ficam pulados se a env nao existir.

## Fora desta fatia

- Webhooks Telegram, WhatsApp Cloud e Discord.
- Outbound real para providers alem de Evolution.
- Campaigns com recipients e jobs de disparo.
- Bots com prompts, regras e execucao.
- Widget publico completo:
  - `GET /widget/{widget_id}/loader.js`
  - `GET /widget/{widget_id}/config`
  - `POST /widget/{widget_id}/messages`
  - `GET /widget/{widget_id}/messages`
- Rate limit para webhooks de providers futuros.
- Audit log de mutations criticas.
