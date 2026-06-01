# Labby Backend A1 - Jobs/outbox foundation

Data: 2026-06-01
Branch: `feature/f3-team-invites-modules`

## Objetivo

Criar a base de processos pesados antes de transplantar Social e Sales.

Decisao aplicada:

- Postgres e a fonte de verdade de estado, idempotencia, retry e auditoria.
- Celery/Redis apenas acorda e executa workers.
- O payload real do job nao depende da fila Redis.

## Entregue nesta fatia

- Migration `003_jobs_outbox_foundation`.
- Modelos SQLAlchemy:
  - `jobs`
  - `job_attempts`
  - `outbox_events`
  - `webhook_events`
  - `rate_limit_events`
- `JobQueueService` com:
  - enqueue idempotente por `tenant_id + job_type + idempotency_key`
  - claim transacional com `FOR UPDATE SKIP LOCKED`
  - registro de attempt
  - sucesso
  - retry com backoff exponencial
  - dead-letter
  - metricas por tenant
  - inserts idempotentes de outbox/webhook
  - auditoria de rate limit
- Runner Celery `labby.jobs.dispatch_due_jobs`.
- Endpoint admin:
  - `GET /api/v2/labby/jobs/metrics`
- Contrato OpenAPI atualizado para metricas de jobs.

## Invariantes

- Todo job tem `tenant_id`.
- `membership_id` e nullable para jobs do sistema.
- Job duplicado retorna o mesmo registro logico pelo unique tenant-scoped.
- Worker sempre faz claim no banco antes de executar.
- Retry nao duplica efeito quando os handlers usam a mesma chave de idempotencia.
- Falha permanente ou estouro de tentativas vira `dead_letter`.
- Webhook bruto fica tenant-scoped e idempotente por provider.
- Rate limit tem trilha auditavel por tenant/provider/chave.

## Arquivos principais

- `app/models/jobs.py`
- `migrations/versions/003_jobs_outbox_foundation.py`
- `app/domains/jobs/job_service.py`
- `app/domains/jobs/registry.py`
- `app/jobs/runner.py`
- `app/api/v2/labby/jobs.py`
- `app/schemas/jobs.py`

## Proximo passo recomendado

Comecar A2 pelo Social atual em fatias pequenas:

1. Mapear o codigo atual do fluxo X/news no OmniiaPro.
2. Criar os primeiros handlers reais usando `JobHandlerRegistry`.
3. Persistir runs/items de curadoria em tabelas Labby tenant-scoped.
4. Trocar chamadas pesadas de request por `enqueue_job`.
5. Manter contrato do frontend onde for possivel.

## Verificacoes rodadas

```powershell
python -m ruff check .
python -m pytest
python -m alembic upgrade head --sql
```

Resultado:

- `ruff`: passou
- `pytest`: `48 passed`
- `alembic --sql`: passou
