# Labby Backend

Backend proprio da Labby.

Este repositorio nasce separado do OmniiaPro para evitar acoplamento entre os produtos. O contrato publico alvo e `/api/v2/labby/*`.

## Estado atual

Branch local: `feature/f3-team-invites-modules`

Backend Python/FastAPI proprio da Labby, sem Docker como requisito de desenvolvimento
ou deploy.

## Fases entregues

Escopo desta fase:

- FastAPI com `/health` e `/api/v2/labby/health`.
- Configuracao `LABBY_*`.
- SQLAlchemy e Alembic.
- Celery + Redis.
- Contrato OpenAPI inicial em `contracts/labby-openapi.yaml`.
- Modelo base de identidade: `users`, `tenants`, `memberships`, `membership_modules`, `team_invites`.
- Auth/memberships com JWT proprio, refresh token opaco e switch tenant.
- Convites de equipe e permissoes por modulo.

Fora de escopo nesta fase:

- Login funcional.
- Convites funcionais.
- Sales/Social.
- Migracao de dados.

## Desenvolvimento local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
```

Healthcheck:

```powershell
Invoke-WebRequest http://localhost:8000/health
```

Worker local, quando precisar processar jobs:

```powershell
celery -A app.core.celery_app.celery_app worker --loglevel=info
```

Beat local, quando precisar agendar jobs:

```powershell
celery -A app.core.celery_app.celery_app beat --loglevel=info
```

Postgres e Redis devem ser servicos gerenciados ou instalados localmente. O projeto
nao depende de Docker.

## Decisoes base

- Auth proprio da Labby.
- JWT com `user_id`, `tenant_id` ativo e `membership_id` ativa.
- Modulos: `sales` e `social_media`.
- FKs operacionais de atores humanos devem apontar para `membership_id`.
- Widget publico canonico: `https://api.labby.com.br/widget/{widget_id}/loader.js`.
