# Labby - Secrets de producao

Data: 2026-06-01

Este documento lista os secrets/configs esperados para producao. Nao commitar
valores reais.

## API

- `LABBY_ENVIRONMENT=production`
- `LABBY_DATABASE_URL`
- `LABBY_REDIS_URL`
- `LABBY_JWT_SECRET`
- `LABBY_JWT_ISSUER`
- `LABBY_JWT_AUDIENCE`
- `LABBY_ALLOWED_ORIGINS`
- `LABBY_APP_BASE_URL`
- `LABBY_TIMEZONE`

Regras:

- `LABBY_JWT_SECRET` deve ter pelo menos 32 caracteres e ser rotacionavel.
- `LABBY_DATABASE_URL` e `LABBY_REDIS_URL` devem apontar para servicos
  gerenciados, nunca `localhost`, em producao.
- `LABBY_ALLOWED_ORIGINS` deve incluir apenas dominios reais da Labby e
  ambientes de preview aprovados.

## Banco

- `LABBY_DATABASE_POOL_SIZE`
- `LABBY_DATABASE_MAX_OVERFLOW`
- `LABBY_DATABASE_POOL_TIMEOUT_SECONDS`
- `LABBY_DATABASE_POOL_RECYCLE_SECONDS`

Regras:

- Dimensionar pool considerando numero de instancias API, workers e limite do
  Postgres gerenciado.
- Workers devem ter pool separado da API quando rodarem como processos
  independentes.

## Email

- `LABBY_EMAIL_FROM`
- `LABBY_RESEND_API_KEY`

Regras:

- `LABBY_EMAIL_FROM` deve usar dominio validado no Resend.
- Bounce/complaint webhooks devem ser persistidos antes de processar.

## Social atual A2

Secrets previstos para as proximas fatias:

- `LABBY_X_API_PROVIDER`
- `LABBY_X_API_KEY`
- `LABBY_X_API_BASE_URL`
- `LABBY_AI_PROVIDER`
- `LABBY_AI_API_KEY`
- `LABBY_AI_MODEL_DEFAULT`

Regras:

- Toda chamada externa precisa de timeout.
- Retry deve acontecer por job, nao dentro da request HTTP.
- Logs devem incluir `tenant_id`, `job_id`, `provider` e `external_id` quando
  existir.

## GitHub

Configurar em `Settings > Secrets and variables > Actions` apenas se a CI passar
a precisar de secrets reais. A CI atual nao deve depender de secrets de
producao.
