# Labby Backend F3 - Team invites e permissoes por modulo

Data: 2026-05-29
Branch: `feature/f3-team-invites-modules`
Base: F2 `22eb4e0`

## Objetivo

Implementar o fluxo de equipe que o frontend da Labby ja chama:

- `/api/v2/labby/modules/*`
- `/api/v2/labby/team/invites/*`
- permissao por modulo `sales` e `social_media`
- convite publico por token
- aceite de convite criando membership no tenant certo
- suporte a usuario existente com novo membership, sem criar user duplicado

Tambem absorve os 3 hardenings recomendados na review da F2.

## Hardening F2 incluido nesta fase

1. `switch-tenant` agora recebe o refresh cookie atual e revoga a sessao antiga depois de emitir a nova.
2. Reset de senha revoga todas as familias de refresh conhecidas do usuario via indice Redis `refresh-user:{user_id}:families`.
3. Login usa hash dummy quando o email nao existe para reduzir enumeracao por timing.

Extra importante encontrado no caminho:

- Removi `passlib[bcrypt]` e passei para `bcrypt` direto com pre-hash SHA-256. O ambiente atual quebrava ao tentar gerar hash real com Passlib + bcrypt novo, entao F2 podia passar com fakes e falhar em registro/login reais.
- `get_current_membership` agora valida tambem `tenants.ativo = true`, bloqueando token antigo de tenant desativado.

## Arquivos principais

- `app/api/v2/labby/modules.py`
- `app/api/v2/labby/team.py`
- `app/domains/access/module_service.py`
- `app/domains/team/team_service.py`
- `app/integrations/email.py`
- `app/schemas/modules.py`
- `app/schemas/team.py`
- `contracts/labby-openapi.yaml`

## Endpoints implementados

### Modulos

- `GET /api/v2/labby/modules/`
- `GET /api/v2/labby/modules/users`
- `PATCH /api/v2/labby/modules/users/{user_id}`

### Convites

- `GET /api/v2/labby/team/invites`
- `POST /api/v2/labby/team/invites`
- `POST /api/v2/labby/team/invites/{invite_id}/resend`
- `POST /api/v2/labby/team/invites/{invite_id}/revoke`
- `GET /api/v2/labby/team/invites/accept/{token}`
- `POST /api/v2/labby/team/invites/accept/{token}`

## Invariantes

- Listagem e mutacao de equipe exigem `owner` ou `admin`.
- Admin so pode conceder/convidar modulos que ele mesmo possui.
- Owner pode conceder/convidar qualquer modulo valido.
- `module_keys` nao pode ficar vazio.
- `default_module` precisa estar dentro de `module_keys`.
- Convite pendente e unico por `tenant_id + email_normalized`, garantido pelo indice parcial da migration F1.
- Criar convite para email que ja e membro ativo do tenant retorna `409`.
- Aceite de convite usa `SELECT ... FOR UPDATE` no convite para evitar duplo aceite em corrida.
- Usuario existente precisa confirmar a senha atual; o aceite cria apenas uma nova membership.
- Usuario novo e criado com `email_verified_at = NOW()` porque o token chegou pelo email do convite.
- Token publico de convite nunca e salvo em claro; so `token_hash`.

## Email

`EmailService` envia via Resend quando `LABBY_RESEND_API_KEY` estiver configurada.

Novas configs:

- `LABBY_APP_BASE_URL`, default `https://app.labby.com.br`
- `LABBY_EMAIL_FROM`, default `Labby <convites@labby.com.br>`
- `LABBY_RESEND_API_KEY`

Se a chave nao estiver configurada, o convite continua criado e a resposta vem com:

- `email_sent=false`
- `email_error="RESEND_API_KEY nao configurada"`

## Escalabilidade e N+1

- `GET /modules/users` usa uma query com `array_agg` para modulos, uma query de count e uma query de stats. Nao faz loop por usuario.
- `GET /team/invites` usa uma query com joins para convidador, uma query de count e monta modulos a partir do JSONB ja carregado.
- Mutacao de modulos faz delete/insert em lote pequeno por membership; volume esperado e baixo por usuario.
- Aceite de convite trava apenas a linha do convite com `FOR UPDATE`.

## Code review Codex

Achados corrigidos durante a propria revisao:

- `LabbyUserModule.id` precisava ser `users.id`, nao `memberships.id`, porque o frontend compara com `user.id` e chama `/modules/users/{user_id}`.
- `get_current_membership` nao validava tenant ativo.
- `ModuleService` e `TeamService` podiam acessar `modules[0]` antes de validar lista vazia.
- O contrato OpenAPI estava com respostas genericas para F3; foi expandido com schemas reais.
- HTML de email agora usa `html.escape` para nome, tenant e URL.

Sem findings bloqueadores abertos no diff atual.

## Testes adicionados

- `tests/test_modules_routes.py`
- `tests/test_team_routes.py`
- `tests/test_team_service.py`

Testes atualizados:

- `tests/test_auth_routes.py`
- `tests/test_security.py`
- `tests/test_token_store.py`
- `tests/test_identity_helpers.py`

## Verificacoes rodadas

```powershell
python -m ruff check .
python -m pytest -q
python -m compileall app tests migrations
python -m alembic upgrade head --sql
python -c "import yaml; yaml.safe_load(open('contracts/labby-openapi.yaml', encoding='utf-8')); print('openapi ok')"
# busca por marcas antigas no repo
git diff --check
```

Resultado:

- `ruff`: passou
- `pytest`: `36 passed`
- `compileall`: passou
- `alembic --sql`: passou
- OpenAPI YAML: parse OK
- Busca Omniia/Jarvis/OmniaFlow: zero ocorrencias
- `git diff --check`: passou

## Pontos para Claude revisar

1. O aceite de convite para usuario existente deve mesmo exigir senha atual, em vez de sobrescrever senha?
2. Admin poder editar/convidar apenas dentro dos proprios modulos esta suficiente para o modelo Labby?
3. Bloquear alteracao de modulos do `owner` e a decisao correta para evitar lockout?
4. O email via Resend deve virar obrigatorio em production ou manter degrade gracioso com `email_sent=false`?
5. A combinacao `SELECT ... FOR UPDATE` + unique membership cobre o duplo aceite do mesmo convite?
