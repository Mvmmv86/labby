# Labby Backend F2 - Auth e memberships

Data: 2026-05-29
Branch: `feature/f2-auth-memberships`
Base: F1 `8fcdffc`

## Objetivo

Implementar o primeiro fluxo funcional de identidade da Labby no backend proprio:

- registro criando `user + tenant + membership owner`
- login com tenant/membership default
- JWT proprio com `user_id`, `tenant_id`, `membership_id`, `role`, `modules`, `iss`, `aud`, `jti`
- refresh token opaco com rotacao e deteccao de reuse via Redis
- cookie httpOnly para refresh cross-subdominio
- `GET /me` com usuario, tenant ativo e memberships disponiveis
- `POST /switch-tenant`
- forgot/reset password com token opaco single-use

## Arquivos principais

- `app/api/v2/labby/auth.py`
- `app/domains/identity/auth_service.py`
- `app/domains/identity/token_store.py`
- `app/domains/identity/modules.py`
- `app/domains/identity/normalization.py`
- `app/schemas/auth.py`
- `app/core/security.py`
- `app/core/redis.py`
- `contracts/labby-openapi.yaml`
- `tests/test_auth_routes.py`
- `tests/test_token_store.py`
- `tests/test_identity_helpers.py`
- `tests/test_security.py`

## Endpoints

Prefixo: `/api/v2/labby/auth`

- `POST /register`
- `POST /login`
- `POST /refresh`
- `POST /logout`
- `GET /me`
- `POST /switch-tenant`
- `POST /forgot-password`
- `POST /reset-password`

## Decisoes de seguranca e concorrencia

- Access token e JWT assinado com `LABBY_JWT_SECRET`, `iss=labby-api`, `aud=labby-app`.
- Refresh token nao e JWT: e opaco, salvo no Redis por hash SHA-256.
- Rotacao de refresh usa `WATCH/MULTI` no Redis. Duas rotacoes paralelas do mesmo token fazem uma vencer; a outra detecta reuse e revoga a familia.
- Reuso de refresh token antigo revoga a familia inteira, bloqueando tambem o token novo emitido antes.
- Reset password usa `GETDEL` no Redis para consumo atomico e single-use.
- Refresh cookie e `HttpOnly`, path `/api/v2/labby/auth`, `SameSite=None` e `Secure` em ambientes protegidos; em dev usa `SameSite=Lax`.
- `forgot-password` responde sempre `204`, sem revelar se o email existe.

## Escopo adiado de proposito

- Envio real do email de reset ainda nao foi conectado; o token ja e gerado no service.
- Convites de time ficam para F3.
- Blacklist de access token nao foi adicionada, porque access token e curto e logout revoga refresh.
- Testes de service contra Postgres real ficam para fase de integracao; os testes de rota usam fake service para nao exigir infraestrutura local.

## Verificacoes rodadas

```powershell
python -m ruff check .
python -m pytest -q
python -m compileall app tests migrations
```

Resultado atual:

- `ruff`: passou
- `pytest`: `24 passed`
- `compileall`: passou

## Pontos para review do Claude

1. A modelagem `user + tenant + membership` esta coerente com usuarios convidados em mais de uma area/tenant?
2. A rotacao Redis com `WATCH/MULTI` cobre a janela de race relevante para refresh token?
3. O contrato de cookie esta correto para `app.labby.com.br` chamando `api.labby.com.br`?
4. Devemos permitir `register` criar novo tenant para um email ja existente ou manter isso para fluxo futuro?
5. O `GET /me` traz o minimo necessario para o frontend trocar entre tenants sem criar N+1?
