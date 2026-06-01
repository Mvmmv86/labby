# A2 - Social atual: handoff tecnico

Data: 2026-06-01

## Entregue

- Migration `004_social_news_foundation`.
- Migration `005_social_news_schedules`.
- Modelos SQLAlchemy para:
  - `social_news_segments`
  - `social_news_sources`
  - `social_news_curators`
  - `social_news_runs`
  - `social_news_items`
  - `social_news_subscribers`
  - `social_news_subscriber_consent_events`
  - `social_news_dispatches`
  - `social_news_schedules`
- `SocialNewsService` tenant-scoped.
- Endpoints em `/api/v2/labby/social/news/*`.
- Endpoints compativeis com frontend para segmentos, sources, curator,
  schedules, runs manuais/listagem/detalhe, subscribers flat/import CSV e
  unsubscribe status/confirmacao.
- Criacao de runs por job idempotente `social.news.capture`.
- Enqueue de rewrite por job `social.news.rewrite`.
- Enqueue de dispatch por job `social.news.dispatch`.
- Handlers registrados para `social.news.capture`, `social.news.rewrite` e
  `social.news.dispatch`.
- Adapter X standalone para TwitterAPI.io com `LABBY_*`.
- Captura X por worker com dedupe, filtro anti-spam simples, ranking por
  engagement e persistencia em `social_news_items`.
- Dispatch por worker usando Resend via `EmailService.send_email`.
- Subscribers com token de unsubscribe assinado e hash persistido.
- Fila de curadoria por endpoints de listagem geral de itens.
- Aliases de curadoria compativeis com o frontend atual em
  `/api/v2/labby/social/news/curation/*`.
- Aliases de curadoria devolvem campos/status no contrato legado do frontend
  (`autor_handle`, `conteudo_original`, `reescrito`, `aprovado_stage2`, etc.),
  sem mudar o modelo interno em ingles.
- Aprovacao/rejeicao stage 1 e stage 2 com transicoes tenant-scoped.
- Aprovacao stage 1 enfileira rewrite idempotente no `worker-ai` na mesma
  transacao de banco da mudanca de status.
- Rewrite tenta IA standalone via OpenAI Responses API quando
  `LABBY_AI_PROVIDER=openai` e `LABBY_AI_API_KEY` estao configurados.
- Rewrite mantém fallback editorial persistido se a IA estiver desabilitada,
  mal configurada ou indisponivel.
- Rewrite ja persistido e tratado como idempotente no worker para evitar
  double-cost em retry/reaper.
- Custo de IA usa tokens retornados pelo provider e os configs
  `LABBY_AI_INPUT_COST_PER_MILLION_TOKENS` e
  `LABBY_AI_OUTPUT_COST_PER_MILLION_TOKENS`.
- Testes de modelos, service e rotas.
- Teste E2E de contrato frontend para o fluxo stage 1 -> rewrite -> stage 2 ->
  dispatch.
- Teste de paridade das rotas sociais que o frontend atual chama.
- Teste cross-tenant negativo explicito para leitura de item tenant-scoped.

## Contrato da fatia

A API nao executa captura do X, IA nem envio de email dentro da request.

Fluxo atual:

1. API valida membership e modulo `social_media`.
2. API cria ou reutiliza run idempotente.
3. API cria job no A1 (`jobs`) com payload tenant-scoped.
4. Worker especifico processa captura, rewrite ou dispatch.

## Jobs criados

- `social.news.capture` na fila `worker-social-ingestion`.
- `social.news.rewrite` na fila `worker-ai`.
- `social.news.dispatch` na fila `worker-email`.

O dispatcher tambem roda um reaper para jobs presos em `running`, controlado por
`LABBY_JOB_RUNNING_TIMEOUT_SECONDS` e `LABBY_JOB_REAPER_BATCH_SIZE`.

## Contrato compativel com frontend atual

- `GET /api/v2/labby/social/news/segments`
- `GET /api/v2/labby/social/news/segments/{segment_id}`
- `POST /api/v2/labby/social/news/segments`
- `POST /api/v2/labby/social/news/segments/from-seed`
- `PATCH /api/v2/labby/social/news/segments/{segment_id}`
- `DELETE /api/v2/labby/social/news/segments/{segment_id}`
- `GET /api/v2/labby/social/news/segments/{segment_id}/sources`
- `POST /api/v2/labby/social/news/segments/{segment_id}/sources`
- `DELETE /api/v2/labby/social/news/sources/{source_id}`
- `GET /api/v2/labby/social/news/segments/{segment_id}/curator`
- `PUT /api/v2/labby/social/news/segments/{segment_id}/curator`
- `POST /api/v2/labby/social/news/runs/manual`
- `GET /api/v2/labby/social/news/runs`
- `GET /api/v2/labby/social/news/runs/{run_id}`
- `GET /api/v2/labby/social/news/runs/{run_id}/items`
- `GET /api/v2/labby/social/news/segments/{segment_id}/schedules`
- `POST /api/v2/labby/social/news/segments/{segment_id}/schedules/recalibrate`
- `PATCH /api/v2/labby/social/news/schedules/{schedule_id}`
- `DELETE /api/v2/labby/social/news/schedules/{schedule_id}`
- `GET /api/v2/labby/social/news/curation/stage1`
- `GET /api/v2/labby/social/news/curation/stage2`
- `GET /api/v2/labby/social/news/curation/ready`
- `GET /api/v2/labby/social/news/curation/dispatch-config`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/stage1`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/rewrite`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/stage2`
- `POST /api/v2/labby/social/news/curation/runs/{run_id}/dispatch`
- `GET /api/v2/labby/social/news/curation/dispatches`
- `GET /api/v2/labby/social/news/subscribers`
- `POST /api/v2/labby/social/news/subscribers`
- `POST /api/v2/labby/social/news/subscribers/import-csv`
- `PATCH /api/v2/labby/social/news/subscribers/{subscriber_id}`
- `DELETE /api/v2/labby/social/news/subscribers/{subscriber_id}`
- `GET /api/v2/labby/social/news/unsubscribe/{token}`
- `POST /api/v2/labby/social/news/unsubscribe/{token}`

## Proxima fatia

Proximas fatias:

1. Smoke real X -> IA -> digest com secrets `LABBY_X_*`, `LABBY_AI_*` e
   `LABBY_RESEND_*` em ambiente controlado.
2. Classificacao por tipo de evento via IA.
3. Webhooks de bounce/complaint do Resend persistidos em `webhook_events`.
