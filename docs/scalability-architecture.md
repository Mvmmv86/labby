# Labby Backend - Escalabilidade

Data: 2026-05-29

## Alvo

Arquitetura preparada para crescer acima de 500 usuarios sem misturar Labby com
OmniiaPro e sem depender de Docker.

## Topologia recomendada

- API FastAPI stateless, com 2+ instancias quando entrar em producao real.
- Postgres gerenciado, com pool de conexoes configurado por env.
- Redis gerenciado para refresh/session state, filas e locks leves.
- Celery workers separados da API para processos pesados.
- Celery beat separado para agendamentos.
- Frontend/landing continuam na Vercel.
- `api.labby.com.br` aponta para o runtime Python da API.

## Configuracao de conexoes

Variaveis:

- `LABBY_DATABASE_POOL_SIZE`
- `LABBY_DATABASE_MAX_OVERFLOW`
- `LABBY_DATABASE_POOL_TIMEOUT_SECONDS`
- `LABBY_DATABASE_POOL_RECYCLE_SECONDS`

Defaults atuais: pool 10, overflow 20, timeout 30s, recycle 1800s.

Com 2 instancias de API, isso pode abrir ate 60 conexoes simultaneas no pico
somando pool + overflow. O limite do Postgres precisa ser dimensionado junto com
workers Celery.

## Banco

F1 criou as constraints de integridade:

- usuario unico por email normalizado
- tenant unico por slug
- uma membership por `user_id + tenant_id`
- um convite pendente por `tenant_id + email_normalized`
- token de convite unico por hash

A migration `002_scalability_indexes` adiciona indices compostos para os acessos atuais:

- `memberships(tenant_id, status, created_at)`
- `memberships(user_id, status, last_access_at)`
- `membership_modules(module_key, membership_id)`
- `team_invites(tenant_id, status, created_at)`
- `team_invites(tenant_id, email_normalized, status)`
- `team_invites(expires_at)` parcial para pendentes

## N+1

Os endpoints atuais evitam N+1:

- `/modules/users` agrega modulos com `array_agg`.
- `/team/invites` faz joins para convidador e usa `module_keys` do JSONB ja carregado.
- `/auth/me` agrega memberships/modulos em consultas agrupadas.

## Processos pesados

O gargalo real da Labby nao sera 500 usuarios logados; sera Social Media:

- captura do X
- curadoria IA
- reescrita/geracao de noticias
- envio de digest
- webhooks/canais de venda

Esses fluxos devem rodar sempre em workers, nunca dentro da request principal.
Cada job precisa ter:

- `tenant_id`
- `membership_id` ou ator do sistema
- chave de idempotencia
- status persistido no banco
- retry com backoff
- limite por tenant para nao deixar um cliente consumir a fila inteira

## Proximos hardenings antes de muitos clientes

1. Adicionar tabelas de jobs/outbox por dominio antes do Social Media completo.
2. Adicionar rate limit por tenant/usuario em auth, convites e jobs caros.
3. Adicionar indices tenant-scoped em todas as futuras tabelas de Sales/Social.
4. Definir metricas: tempo de request, fila Celery, jobs com erro, uso de Redis e conexoes DB.
5. Rodar load test antes do cutover de `api.labby.com.br`.
