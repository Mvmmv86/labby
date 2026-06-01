# A2 - Social atual: handoff tecnico

Data: 2026-06-01

## Entregue

- Migration `004_social_news_foundation`.
- Modelos SQLAlchemy para:
  - `social_news_segments`
  - `social_news_sources`
  - `social_news_curators`
  - `social_news_runs`
  - `social_news_items`
  - `social_news_subscribers`
  - `social_news_subscriber_consent_events`
  - `social_news_dispatches`
- `SocialNewsService` tenant-scoped.
- Endpoints em `/api/v2/labby/social/news/*`.
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

- `GET /api/v2/labby/social/news/curation/stage1`
- `GET /api/v2/labby/social/news/curation/stage2`
- `GET /api/v2/labby/social/news/curation/ready`
- `GET /api/v2/labby/social/news/curation/dispatch-config`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/stage1`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/rewrite`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/stage2`
- `POST /api/v2/labby/social/news/curation/runs/{run_id}/dispatch`
- `GET /api/v2/labby/social/news/curation/dispatches`

## Proxima fatia

Proximas fatias:

1. Classificacao por tipo de evento via IA.
2. E2E X -> IA -> digest com providers reais em ambiente controlado.
3. Webhooks de bounce/complaint do Resend persistidos em `webhook_events`.
