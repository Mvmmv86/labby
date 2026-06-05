# A5 Observabilidade e Load Test - Handoff Inicial

Data: 2026-06-05
Branch: `feature/f3-team-invites-modules`

## Escopo entregue

Primeiro corte de A5 focado nas rotas publicas e no crescimento operacional de
tabelas de auditoria.

Inclui:

- Rate limiter Redis de janela fixa em `app/core/rate_limit.py`.
- O limiter Redis usa Lua script atomico para `INCR` + `EXPIRE` + `TTL`,
  evitando chave sem TTL se o processo cair no primeiro incremento.
- Config `LABBY_PUBLIC_RATE_LIMIT_BACKEND` com valores `database` ou `redis`.
- Em `staging`/`production`, `LABBY_PUBLIC_RATE_LIMIT_BACKEND=redis` passa a
  ser obrigatorio.
- Cliente Redis e singleton por processo para evitar criar pool/conexao por
  request no hot path publico.
- Widget publico e webhook Evolution aceitam limiter injetado e usam Redis
  quando configurado.
- Quando Redis permite a requisicao, nao ha insert em `rate_limit_events`.
- Quando Redis bloqueia, um evento `blocked` continua sendo persistido para
  auditoria.
- Fallback por Postgres permanece disponivel em desenvolvimento/testes.
- Webhook Evolution degrada para o fallback por Postgres se Redis estiver
  indisponivel, para nao perder inbound durante outage curto do Redis.
- Widget publico falha fechado com `503` quando Redis estiver indisponivel.
- Cleanup operacional para:
  - `rate_limit_events` antigos;
  - `sales_message_dispatch_attempts` finalizados antigos.
- Task Celery `labby.jobs.cleanup_operational_history`.
- Celery beat agenda o cleanup pelo intervalo configuravel.
- Retry seguro de outbound Evolution com consulta em
  `/chat/findMessages/{instance}` antes de reenviar.

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
- `LABBY_SALES_OUTBOUND_RECONCILIATION_GRACE_SECONDS`
  - default: `60`.

## Decisoes

- Rotas publicas nao devem gravar uma linha no banco para cada request
  permitido quando Redis estiver ativo.
- Bloqueios ainda entram em `rate_limit_events` para auditoria, alerta e
  investigacao.
- Webhook de provider e diferente de widget: o webhook pode cair para DB em
  outage de Redis porque perder inbound e pior que aumentar escrita
  temporariamente; o widget continua fail-closed.
- Cleanup nao remove attempts em `sending`; apenas attempts finalizados
  (`sent`, `failed`, `skipped`) entram na retencao.
- Jobs de outbound Evolution usam retry, mas nunca reenviam uma mensagem em
  `sending` sem antes consultar o provider.
- Resultado desconhecido (`timeout`, erro de transporte ou 5xx) mantem a
  mensagem em `sending`; erro definitivo do provider segue marcando `failed`.

## Testes adicionados

- `tests/test_rate_limit.py`
  - Redis fixed window usa `eval` atomico, conta e expira chave;
  - Redis indisponivel falha fechado.
- `tests/test_rate_limit.py`
  - `make_redis_client` reutiliza singleton por processo.
- `tests/test_config.py`
  - staging exige `LABBY_PUBLIC_RATE_LIMIT_BACKEND=redis`;
  - staging aceita backend Redis com dependencias gerenciadas.
- `tests/test_job_service.py`
  - cleanup operacional usa retencao e limite.
- `tests/test_sales_bots_widget_integration.py`
  - widget com Redis nao grava evento permitido;
  - widget com Redis grava evento bloqueado;
  - widget com Redis indisponivel responde `503` sem fallback por DB.
- `tests/test_sales_webhooks_integration.py`
  - webhook Evolution com Redis nao grava evento permitido;
  - webhook Evolution com Redis grava evento bloqueado;
  - webhook Evolution com Redis indisponivel cai para o rate limit por DB.
- `tests/test_sales_outbound_integration.py`
  - delivery unknown fica em `sending`;
  - retry encontrado no provider reconcilia sem reenvio;
  - retry nao encontrado aguarda janela antes de reenviar;
  - reenvio so acontece apos consulta de reconciliacao.

## Pendencias de A5/A6

- Retry seguro de outbound com consulta/reconciliacao no Evolution antes de
  reenviar mensagem possivelmente entregue foi iniciado nesta fatia; ainda deve
  passar por smoke real com Evolution.
- Alertas reais sobre `sales_outbound_stuck`, filas paradas, jobs falhos e
  rate limit bloqueado.
- Metricas de request latency/error rate, DB pool usage e Redis latency.
- Load test 500 usuarios/50 tenants com Social e Sales.
- Definir se Telegram, WhatsApp Cloud e Discord entram no MVP ou ficam
  bloqueados ate pos-cutover.
