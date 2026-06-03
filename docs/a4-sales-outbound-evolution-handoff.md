# A4 Sales - Outbound Evolution Handoff

Data: 2026-06-03
Branch: `feature/f3-team-invites-modules`

## Escopo entregue

Fatia de integracao standalone para envio real de mensagens de Sales via
Evolution, cobrindo inbox manual e campanhas.

Inclui:

- Migration `010_sales_outbound_dispatch`.
- Novas colunas em `sales_messages`:
  - `delivery_provider`
  - `delivery_external_id`
  - `dispatched_at`
- Novo status intermediario `sending` em `sales_messages`.
- Tabela `sales_message_dispatch_attempts`.
- Handler de job `sales.message.dispatch` em
  `app/domains/sales/outbound_jobs.py`.
- Queue `worker-sales-outbound`.
- Adapter Evolution outbound em `app/integrations/sales_channels.py`.
- Rate limit auditavel do webhook publico Evolution via `rate_limit_events`.

## Decisoes

- `sales_messages.provider/external_id` continuam podendo representar o id
  interno de dedupe da Labby, como `labby_campaign`.
- O id real do provider fica separado em
  `delivery_provider/delivery_external_id`, evitando quebrar a idempotencia de
  campanhas quando o provider retorna outro id.
- `delivery_provider + delivery_external_id` tem unique parcial por tenant para
  reconciliacao de provider.
- Inbox manual e worker de campanhas enfileiram `sales.message.dispatch` na
  mesma transacao em que a mensagem `pending` nasce.
- O worker cria uma tentativa unica por provider/idempotency key em
  `sales_message_dispatch_attempts`.
- Antes de chamar o provider, a mensagem muda para `sending`. Se o worker cair
  nesse ponto, retry automatico nao reenvia cegamente; a mensagem e marcada
  para reconciliacao/falha em vez de arriscar double-send.
- Quando Evolution retorna id externo, o worker marca a mensagem como `sent`,
  preenche `delivery_provider/delivery_external_id` e atualiza recipients de
  campanha para `sent`.
- Webhook `messages.update` reconcilia status tanto por
  `provider/external_id` antigo quanto por
  `delivery_provider/delivery_external_id`.

## Evolution

- O adapter usa `LABBY_EVOLUTION_API_URL`, `LABBY_EVOLUTION_API_KEY` e
  `LABBY_EVOLUTION_API_TIMEOUT_SECONDS`.
- Mensagens `text` usam `/message/sendText/{instance_name}`.
- Midias com `media_url` usam `/message/sendMedia/{instance_name}`.
- O payload inclui `metadata.labby_idempotency_key` para auditoria e eventual
  suporte de idempotencia pelo provider.
- O destinatario e derivado de `sales_contact_channels.identifier` quando
  existe, com fallback para telefone do contato.

## Rate Limit do Webhook Evolution

- O endpoint publico agora passa IP confiavel pelo ultimo hop de
  `X-Forwarded-For`, com fallback `X-Real-IP`, para auditoria.
- O receiver valida o segredo por comparacao constante antes de qualquer
  evento/job de dominio.
- Depois do secret valido, aplica cap auditavel por `channel_id`.
- Nao ha limite por IP no Evolution webhook, porque o provider pode entregar
  todo o trafego legitimo por uma unica origem e um gargalo por IP perderia
  mensagens inbound.

## Testes adicionados

- `tests/test_sales_outbound_integration.py`
  - handler registrado;
  - envio manual cria job de outbound;
  - worker chama Evolution uma unica vez;
  - reprocessamento nao reenvia;
  - mensagem grava `delivery_provider/delivery_external_id`;
  - webhook de status reconcilia por id externo de delivery.
- `tests/test_sales_webhooks_integration.py`
  - rate limit do webhook Evolution por canal;
  - secret invalido nao consome quota de canal.
- `tests/test_sales_webhook_routes.py`
  - rota publica deriva IP confiavel do ultimo hop do `X-Forwarded-For`.
- `tests/test_sales_models.py`
  - tabela de attempts registrada;
  - unique parcial de delivery;
  - unique de attempts por provider/idempotency key.

## Pendencias conscientes

- Receivers inbound de Telegram, WhatsApp Cloud e Discord seguem bloqueados em
  `connect` ate suas rotas existirem.
- Outbound real para Telegram, WhatsApp Cloud e Discord ainda nao foi
  implementado.
- Targeting de campanha por `filtro_tags`/`filtro_grupo` segue deferido.
- Retencao de `rate_limit_events` e `sales_message_dispatch_attempts` deve
  entrar em A5.
- Observabilidade agregada por provider/fila ainda entra em A5.
