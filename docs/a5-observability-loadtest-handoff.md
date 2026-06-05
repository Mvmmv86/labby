# A5 Observabilidade e Load Test - Handoff Inicial

Data: 2026-06-05
Branch: `feature/f3-team-invites-modules`

## Escopo entregue

Primeiro corte de A5 focado nas rotas publicas e no crescimento operacional de
tabelas de auditoria.

Inclui:

- Rate limiter Redis de janela fixa em `app/core/rate_limit.py`.
- Config `LABBY_PUBLIC_RATE_LIMIT_BACKEND` com valores `database` ou `redis`.
- Em `staging`/`production`, `LABBY_PUBLIC_RATE_LIMIT_BACKEND=redis` passa a
  ser obrigatorio.
- Widget publico e webhook Evolution aceitam limiter injetado e usam Redis
  quando configurado.
- Quando Redis permite a requisicao, nao ha insert em `rate_limit_events`.
- Quando Redis bloqueia, um evento `blocked` continua sendo persistido para
  auditoria.
- Fallback por Postgres permanece disponivel em desenvolvimento/testes.
- Cleanup operacional para:
  - `rate_limit_events` antigos;
  - `sales_message_dispatch_attempts` finalizados antigos.
- Task Celery `labby.jobs.cleanup_operational_history`.
- Celery beat agenda o cleanup pelo intervalo configuravel.

## Configuracoes novas

- `LABBY_PUBLIC_RATE_LIMIT_BACKEND`
  - `database`: fallback/dev.
  - `redis`: requerido fora de desenvolvimento.
- `LABBY_RATE_LIMIT_EVENTS_RETENTION_DAYS`
  - default: `14`.
- `LABBY_SALES_DISPATCH_ATTEMPT_RETENTION_DAYS`
  - default: `90`.
- `LABBY_OPERATIONAL_HISTORY_CLEANUP_BATCH_SIZE`
  - default: `1000`.
- `LABBY_OPERATIONAL_HISTORY_CLEANUP_INTERVAL_SECONDS`
  - default: `3600`.

## Decisoes

- Rotas publicas nao devem gravar uma linha no banco para cada request
  permitido quando Redis estiver ativo.
- Bloqueios ainda entram em `rate_limit_events` para auditoria, alerta e
  investigacao.
- Cleanup nao remove attempts em `sending`; apenas attempts finalizados
  (`sent`, `failed`, `skipped`) entram na retencao.
- Retry automatico de outbound Evolution ainda nao foi aumentado. O sistema
  continua fail-closed ate existir consulta/reconciliacao confiavel no provider
  antes de reenviar.

## Testes adicionados

- `tests/test_rate_limit.py`
  - Redis fixed window conta e expira chave;
  - Redis indisponivel falha fechado.
- `tests/test_config.py`
  - staging exige `LABBY_PUBLIC_RATE_LIMIT_BACKEND=redis`;
  - staging aceita backend Redis com dependencias gerenciadas.
- `tests/test_job_service.py`
  - cleanup operacional usa retencao e limite.
- `tests/test_sales_bots_widget_integration.py`
  - widget com Redis nao grava evento permitido;
  - widget com Redis grava evento bloqueado.
- `tests/test_sales_webhooks_integration.py`
  - webhook Evolution com Redis nao grava evento permitido;
  - webhook Evolution com Redis grava evento bloqueado.

## Pendencias de A5/A6

- Retry seguro de outbound com consulta/reconciliacao no Evolution antes de
  reenviar mensagem possivelmente entregue.
- Alertas reais sobre `sales_outbound_stuck`, filas paradas, jobs falhos e
  rate limit bloqueado.
- Metricas de request latency/error rate, DB pool usage e Redis latency.
- Load test 500 usuarios/50 tenants com Social e Sales.
- Definir se Telegram, WhatsApp Cloud e Discord entram no MVP ou ficam
  bloqueados ate pos-cutover.
