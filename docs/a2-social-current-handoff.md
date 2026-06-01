# A2 - Social atual: primeira fatia tecnica

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
- Testes de modelos, service e rotas.

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

## Proxima fatia

Proximas fatias:

1. Trocar rewrite fallback por chamada real de IA standalone.
2. Adicionar endpoints de aprovacao/rejeicao stage 1 e stage 2.
3. Classificacao por tipo de evento via IA.
4. E2E X -> IA -> digest.
