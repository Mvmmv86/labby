# Labby Backend

Backend proprio da Labby.

Este repositorio nasce separado do OmniiaPro para evitar acoplamento entre os produtos. O contrato publico alvo e `/api/v2/labby/*`.

## Branch atual

`feature/f1-bootstrap`

## F1 - Bootstrap

Escopo desta fase:

- FastAPI com `/health` e `/api/v2/labby/health`.
- Configuracao `LABBY_*`.
- SQLAlchemy e Alembic.
- Celery + Redis.
- Docker para API, worker, beat, Postgres e Redis.
- Contrato OpenAPI inicial em `contracts/labby-openapi.yaml`.
- Modelo base de identidade: `users`, `tenants`, `memberships`, `membership_modules`, `team_invites`.

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

## Decisoes base

- Auth proprio da Labby.
- JWT com `user_id`, `tenant_id` ativo e `membership_id` ativa.
- Modulos: `sales` e `social_media`.
- FKs operacionais de atores humanos devem apontar para `membership_id`.
- Widget publico canonico: `https://api.labby.com.br/widget/{widget_id}/loader.js`.

