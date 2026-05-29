# F1 Bootstrap - Handoff para review

Data: 2026-05-29
Branch: `feature/f1-bootstrap`
Commit base: `1ef7a74`

## Objetivo

Criar o repositorio proprio `labby-backend` separado do OmniiaPro, com base tecnica para evoluir a Labby sem misturar codigo com OmniiaPro/RH.

## Entregue

- Repo local: `C:\Users\marcu\labby-backend`.
- Branch: `feature/f1-bootstrap`.
- FastAPI com:
  - `GET /health`
  - `GET /api/v2/labby/health`
- Config `LABBY_*` via `pydantic-settings`.
- SQLAlchemy 2 + Alembic.
- Celery + Redis configurados.
- Docker Compose com API, worker, beat, Postgres e Redis.
- CI GitHub Actions com install, ruff e pytest.
- Contrato inicial em `contracts/labby-openapi.yaml`.
- Modelo base de identidade:
  - `users`
  - `tenants`
  - `memberships`
  - `membership_modules`
  - `team_invites`
- Migration inicial:
  - `migrations/versions/001_identity_foundation.py`
- Dependencias estruturais:
  - `get_current_membership`
  - `require_module`
  - `require_role`

## Decisoes implementadas

- `social_media` e a chave de modulo real.
- JWT esperado carrega `user_id`, `tenant_id`, `membership_id`, `role` e `modules`.
- Atores humanos tenant-scoped devem usar `membership_id`.
- Convites armazenam `token_hash`, nao token cru.
- Um convite pendente por `tenant_id + email_normalized` e protegido por indice parcial.
- Widget publico fica fora de `/api/v2/labby` no contrato: `/widget/{widget_id}/loader.js`.

## Fora de escopo

- Endpoints de auth funcionais.
- Refresh token funcional.
- Convite funcional.
- Contacts/Sales.
- Social Media.
- Jobs de negocio.
- Deploy remoto.

## Verificacoes

Rodado:

```powershell
python -m compileall app tests
python -m pytest -q
```

Resultado esperado no ultimo run: `11 passed`.

Rodado apos review:

```powershell
python -m ruff check .
alembic upgrade head --sql
```

Resultado: Ruff limpo e SQL offline gerado com sucesso.

Tentado:

```powershell
docker build -t labby-backend:f1 .
```

Resultado: nao executou porque o Docker Desktop daemon nao estava ativo
(`dockerDesktopLinuxEngine` indisponivel). O Dockerfile foi ajustado para instalar
o pacote depois de copiar o codigo.

## Fixes apos review Claude

Review externo: `docs/plans/2026-05-29-labby-f1-review.md` no repo OmniiaPro.

Correcoes aplicadas:

- B1: corrigido `ruff I001` na migration.
- H1: `Settings` agora faz fail-fast em `production/staging` quando `LABBY_JWT_SECRET` usa o default ou tem menos de 32 chars; tambem bloqueia DB/Redis localhost fora de dev.
- H2: adicionado `/healthz` e `/api/v2/labby/healthz` tocando DB e Redis, retornando 503 quando dependencia falha.
- H3: adicionado Celery smoke task `labby.smoke.ping` com teste em eager mode.
- H4: migration alinhada com models para `nullable=False` e `server_default` em timestamps e defaults de banco.
- M3: `.env.example` documenta issuer, audience, expiração de tokens e timezone.
- M4: Dockerfile ajustado para instalar o pacote depois de copiar o codigo.

## Pontos para review adversarial

1. O modelo `membership_modules` com duas FKs para `memberships` esta corretamente desambiguado?
2. A migration inicial representa fielmente os models e indices necessarios para convites?
3. O contrato inicial OpenAPI esta suficiente para F1 ou deve ficar ainda mais completo antes da F2?
4. Devemos criar tabela de refresh/session ja na F1 ou deixar para F2 Auth?
5. O uso de `membership_id` como ator humano padrao esta consistente com a futura migracao dos dominios `of_*`?
