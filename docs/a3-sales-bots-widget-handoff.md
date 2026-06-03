# A3 Sales - Bots e Widget Publico Handoff

Data: 2026-06-03

## Escopo entregue

- Migration `009_sales_bots_widget_foundation`.
- Tabelas `sales_bots` e `sales_bot_runs`.
- Indice unico parcial `uq_sales_channels_web_chatbot_widget_id` para impedir
  dois widgets publicos com o mesmo `widget_id`.
- Endpoints flat de bots:
  - `GET /api/v2/labby/bots/`
  - `POST /api/v2/labby/bots/`
  - `GET /api/v2/labby/bots/{id}`
  - `PUT /api/v2/labby/bots/{id}`
  - `DELETE /api/v2/labby/bots/{id}`
  - `POST /api/v2/labby/bots/{id}/toggle`
  - `POST /api/v2/labby/bots/{id}/duplicate`
- Endpoints canonicos equivalentes em `/api/v2/labby/sales/bots/*`.
- Widget publico fora de `/api/v2/labby`:
  - `GET /widget/{widget_id}/loader.js`
  - `GET /widget/{widget_id}/config`
  - `POST /widget/{widget_id}/messages`
  - `GET /widget/{widget_id}/messages`

## Invariantes implementados

- Bots sao sempre `tenant_id` scoped.
- Mutations de bots exigem modulo `sales` e role `owner/admin/agent`.
- Respostas mantem campos legados do frontend:
  - `nome`
  - `ativo`
  - `tipo_trigger`
  - `trigger_valor`
  - `channel_ids`
  - `total_acionamentos`
  - `total_concluidos`
  - `total_transferidos`
- Update de bot tolera campos extras do frontend legado.
- Delete de bot bloqueia remocao enquanto estiver ativo.
- Widget resolve `tenant_id` e `channel_id` pelo `widget_id`; o payload publico
  nunca define tenant/canal.
- Widget so funciona para canal `web_chatbot` conectado e ativo.
- `allowed_origins` no `config` do canal e respeitado quando configurado.
- CORS dedicado em `/widget/*` permite embed cross-origin sem cookies ou
  credenciais, mantendo o controle de origem na camada de aplicacao.
- Rate limit auditavel via `rate_limit_events` para envio e polling do widget:
  chave por IP confiavel e backstop por `widget_id`, sem depender de
  `visitor_id` informado pelo cliente.
- Mensagem publica usa provider `web_widget` e `external_id` deterministico com
  `client_message_id`, com `ON CONFLICT DO NOTHING`.
- Reentrega da mesma mensagem do widget nao duplica contato, conversa, mensagem,
  contador nem resposta de bot.
- Contato do visitante e vinculado por `sales_contact_channels.identifier` no
  formato `web:{widget_id}:{visitor_id}`.
- Concorrencia por visitante usa advisory lock transacional.

## Runtime de bot no widget

O widget chama um runtime interno minimo de bots:

- ativa bots `active=true` cujo `channel_ids` contem o canal do widget;
- respeita triggers `todas_mensagens`, `primeira_mensagem` e `keyword`;
- responde com FAQ quando a pergunta bate;
- usa `welcome_message`/`fallback_message` quando aplicavel;
- transfere para humano quando a mensagem indica pedido de atendente humano;
- grava `sales_bot_runs`;
- grava resposta como `sales_messages.sender_type='bot'`.

Importante: esta fatia nao chama IA externa no request publico. O envio para IA
standalone e reconciliacao mais completa ficam para A4/A5, para nao prender o
widget publico em chamada longa ou acoplamento externo.

## Validacao local

- `ruff check .` passou.
- `python -m pytest -q` passou com `112 passed, 5 skipped`.
- `alembic upgrade head --sql` gerou SQL ate `009_sales_bots_widget_foundation`.
- `contracts/labby-openapi.yaml` regenerado e validado com `yaml.safe_load`.

## Pendencias conscientes

- Outbound real para providers alem de Evolution ainda nao foi implementado.
- Webhooks inbound de Telegram, WhatsApp Cloud e Discord seguem bloqueados em
  `connect` ate os receivers existirem.
- Bot com LLM real deve virar job/adapter standalone antes de producao completa.
- Audit log de mutations criticas ainda esta pendente.
- Rate limit para webhooks de providers futuros deve ser consolidado em A5
  antes do A6.
