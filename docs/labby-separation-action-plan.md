# Labby - Plano de Acao Revisado para Separacao 100%

Data: 2026-05-29
Branch local: `feature/f3-team-invites-modules`
Repo local: `C:\Users\marcu\labby-backend`

## Objetivo

Separar a Labby 100% do backend OmniiaPro, mantendo o OmniiaPro protegido e
estavel em producao.

A Labby deve nascer como plataforma propria para:

- Vendas, pre-venda, pos-venda e suporte.
- Social Media com redes sociais pesadas: X, Facebook, Instagram, YouTube,
  LinkedIn e futuras redes.
- Curadoria com IA, captura de eventos, agendamento, publicacao e digest.
- Operacao multi-tenant com mais de 500 usuarios e muitos processos em fila.

Decisao importante: sem Docker como requisito. O backend roda com Python/FastAPI
nativo, Postgres gerenciado, Redis gerenciado e workers separados.

## Estado atual

Ja existe um backend proprio da Labby em `C:\Users\marcu\labby-backend`.

Commits locais relevantes:

- `1065034 chore: add scalability database foundation`
- `a897d73 chore: remove Docker from Labby backend flow`
- `85c8aa0 feat: add team invites and module permissions`
- `22eb4e0 feat: add Labby auth membership foundation`
- `8fcdffc fix: harden F1 bootstrap review findings`
- `ebc4151 chore: add identity foundation migration`
- `1ef7a74 chore: bootstrap Labby backend`

Ainda nao existe remote GitHub configurado. O repo sera criado no GitHub depois.

## O que ja foi entregue

### F1 - Fundacao

- FastAPI.
- Config `LABBY_*`.
- `/health` e `/healthz`.
- SQLAlchemy + Alembic.
- Redis + Celery configurados.
- CI com ruff/pytest.
- OpenAPI inicial.
- Tabelas:
  - `users`
  - `tenants`
  - `memberships`
  - `membership_modules`
  - `team_invites`

### F2 - Auth e memberships

- Register/login/logout/refresh.
- `/auth/me`.
- Switch tenant.
- Reset password.
- JWT proprio com `user_id`, `tenant_id`, `membership_id`, `role`, `modules`.
- Refresh token opaco no Redis, salvo por hash.
- Rotacao de refresh com protecao contra reuse.
- Reset de senha revoga sessoes.
- Login com hash dummy para reduzir enumeracao por timing.

### F3 - Equipe e modulos

- `/api/v2/labby/modules/*`.
- `/api/v2/labby/team/invites/*`.
- Convites por email.
- Token de convite salvo apenas como hash.
- Aceite de convite com `SELECT ... FOR UPDATE`.
- Usuario existente aceita convite criando nova membership, sem duplicar user.
- Permissoes por modulo:
  - `sales`
  - `social_media`

### Hardening de escala ja aplicado

- Pool configuravel de Postgres:
  - `LABBY_DATABASE_POOL_SIZE`
  - `LABBY_DATABASE_MAX_OVERFLOW`
  - `LABBY_DATABASE_POOL_TIMEOUT_SECONDS`
  - `LABBY_DATABASE_POOL_RECYCLE_SECONDS`
- Migration `002_scalability_indexes`.
- Indices compostos:
  - `memberships(tenant_id, status, created_at)`
  - `memberships(user_id, status, last_access_at)`
  - `membership_modules(module_key, membership_id)`
  - `team_invites(tenant_id, status, created_at)`
  - `team_invites(tenant_id, email_normalized, status)`
  - `team_invites(expires_at)` parcial para convites pendentes
- Documento `docs/scalability-architecture.md`.

## Principios arquiteturais

### 1. API stateless

A API nao deve guardar estado em memoria local. Isso permite subir 2+ instancias
da API quando necessario.

Estado vai para:

- Postgres: dados transacionais.
- Redis: refresh/session state, locks leves, filas e rate limits.
- Workers: processamento pesado fora da request.

### 2. Multi-tenant real

Modelo atual:

- `users`: identidade global.
- `tenants`: workspace/cliente.
- `memberships`: relacao usuario + tenant.
- `membership_modules`: modulos liberados por membership.

Isso permite que um usuario participe de mais de um tenant ou area sem duplicar
conta.

### 3. Tudo tenant-scoped

Toda tabela de dominio futura precisa ter `tenant_id`.

Quando houver ator humano, preferir `membership_id` para saber quem fez a acao
dentro daquele tenant.

### 4. Processos pesados sempre em fila

Nenhum processo pesado deve rodar dentro da request HTTP.

A API deve:

- validar permissao;
- criar comando/job;
- persistir estado;
- retornar rapido.

O worker deve:

- executar captura;
- chamar IA;
- enviar email;
- publicar conteudo;
- processar webhook;
- recalcular metricas.

### 5. Idempotencia obrigatoria

Toda integracao externa precisa de chave de idempotencia.

Exemplos:

- webhook recebido duas vezes;
- retry de publicacao;
- reprocessamento de digest;
- refresh de token repetido;
- captura de post/comentario duplicado.

## Topologia de producao recomendada

Sem Docker como requisito.

Componentes:

- Frontend Labby na Vercel: `app.labby.com.br`.
- Landing Labby na Vercel: `labby.com.br`.
- API Python/FastAPI: `api.labby.com.br`.
- Postgres gerenciado.
- Redis gerenciado.
- Worker Celery para jobs.
- Scheduler/Celery beat para rotinas.
- Observabilidade: logs, metricas, alerta de jobs e filas.

Separacao de processos:

- `api`: requests HTTP.
- `worker-social-ingestion`: captura e webhooks.
- `worker-social-publish`: publicacoes/agendamentos.
- `worker-ai`: curadoria, resumo, rewrite, geracao.
- `worker-email`: digest e convites.
- `beat`: agendamentos recorrentes.

## Plano de fases atualizado

### F0 - Repo e governanca

Status: parcialmente feito localmente.

Falta:

- Criar repo GitHub `labby-backend`.
- Configurar `origin`.
- Fazer push da branch atual.
- Definir ambiente de deploy sem Docker.
- Definir Postgres/Redis gerenciados.

Gate:

- Repo remoto criado.
- CI rodando.
- Branch protegida.
- Secrets de producao documentados.

### F1 - Bootstrap tecnico

Status: feito.

Gate ja validado:

- FastAPI sobe.
- Healthcheck funciona.
- Alembic gera SQL.
- CI passa.

### F2 - Auth/memberships

Status: feito.

Gate ja validado:

- Register/login/refresh/logout.
- JWT com tenant/membership.
- Refresh opaco.
- Reset password.
- Switch tenant.

### F3 - Equipe/permissoes

Status: feito.

Gate ja validado:

- Convites.
- Aceite de convite.
- Usuario existente com nova membership.
- Permissoes por modulo.
- Sem N+1 relevante nos endpoints atuais.

### F4 - Fundacao de jobs e outbox

Objetivo: preparar a Labby para processos pesados antes de implementar redes
sociais.

Criar tabelas:

- `jobs`
- `job_attempts`
- `outbox_events`
- `webhook_events`
- `rate_limit_buckets` ou estrutura equivalente em Redis + auditoria no banco

Campos essenciais de `jobs`:

- `id`
- `tenant_id`
- `membership_id` nullable
- `job_type`
- `queue_name`
- `status`
- `priority`
- `idempotency_key`
- `payload`
- `result`
- `error_code`
- `error_message`
- `attempts`
- `max_attempts`
- `run_after`
- `locked_at`
- `locked_by`
- `created_at`
- `updated_at`

Invariantes:

- unique por `tenant_id + job_type + idempotency_key`.
- jobs sempre tenant-scoped.
- retry com backoff.
- dead-letter para falhas permanentes.
- nenhuma request HTTP espera job pesado terminar.

Gate:

- Criar job idempotente.
- Worker processa.
- Retry funciona.
- Job duplicado nao duplica efeito.
- Metricas basicas de fila existem.

### F5 - Fundacao de integracoes sociais

Objetivo: criar base unica para Facebook, Instagram, YouTube, LinkedIn, X e
futuras redes.

Criar tabelas:

- `social_providers`
- `social_accounts`
- `social_account_tokens`
- `social_scopes`
- `social_webhook_subscriptions`
- `social_sync_states`
- `social_external_objects`

`social_accounts` deve conter:

- `tenant_id`
- `provider`
- `provider_account_id`
- `display_name`
- `username`
- `avatar_url`
- `status`
- `connected_by_membership_id`
- `last_sync_at`
- `metadata`

`social_account_tokens` deve conter:

- `social_account_id`
- token criptografado, nunca texto puro
- refresh token criptografado, quando existir
- `expires_at`
- `scopes`
- `status`

Requisitos:

- Criptografia de tokens externos.
- Refresh automatico antes de expirar.
- Revogacao/desconexao segura.
- Validacao de scopes por funcionalidade.
- Rate limit por provider, tenant e conta conectada.

Gate:

- Conectar conta fake/provider stub.
- Salvar token criptografado.
- Renovar token.
- Desconectar conta.
- Bloquear acao sem scope correto.

### F6 - Webhooks sociais

Objetivo: receber eventos das redes sem processar tudo na request.

Fluxo:

1. Endpoint publico recebe webhook.
2. Valida assinatura/verificacao do provider.
3. Persiste evento bruto em `webhook_events`.
4. Retorna rapido.
5. Worker processa e gera jobs derivados.

Requisitos:

- idempotencia por provider event id.
- assinatura por provider.
- rate limit.
- payload bruto preservado.
- status de processamento.

Gate:

- Webhook duplicado nao duplica processamento.
- Webhook invalido e rejeitado.
- Processamento acontece em worker.

### F7 - Social ingestion

Objetivo: capturar dados das redes.

Dados esperados:

- posts
- comentarios
- replies
- mensagens quando a API permitir
- metricas
- mencoes
- midias

Tabelas provaveis:

- `social_posts`
- `social_comments`
- `social_messages`
- `social_metrics_snapshots`
- `social_media_assets`
- `social_mentions`

Invariantes:

- unique por `tenant_id + provider + external_id`.
- indice por `tenant_id + social_account_id + created_at`.
- nao duplicar post/comentario em retry.
- separar conteudo bruto de conteudo processado pela IA.

Gate:

- sync incremental.
- deduplicacao.
- paginacao/cursor por provider.
- retry sem duplicar dados.

### F8 - Social publishing e calendario

Objetivo: agendar e publicar conteudo.

Tabelas provaveis:

- `social_publication_plans`
- `social_scheduled_posts`
- `social_publish_attempts`
- `social_post_variants`

Requisitos:

- status de publicacao.
- tentativa por provider.
- idempotencia por publicacao.
- preview antes de publicar.
- logs de erro por provider.
- respeitar rate limits.

Gate:

- criar post agendado.
- worker publica.
- erro gera retry/backoff.
- publicacao duplicada e bloqueada.

### F9 - IA e curadoria social

Objetivo: estruturar IA sem travar request e sem misturar dados de tenants.

Tabelas provaveis:

- `ai_runs`
- `ai_run_inputs`
- `ai_run_outputs`
- `ai_prompt_versions`
- `ai_content_suggestions`
- `ai_content_reviews`

Invariantes:

- todo run tem `tenant_id`.
- prompt versionado.
- output persistido.
- aceite humano separado do output da IA.
- custo/token tracking por tenant.
- limites por plano.

Gate:

- IA roda via job.
- resultado persistido.
- aceite humano gera acao.
- falha da IA nao quebra fluxo principal.

### F10 - Digest/email/newsletter

Objetivo: evoluir o digest atual para estrutura escalavel.

Tabelas provaveis:

- `email_audiences`
- `email_subscribers`
- `email_campaigns`
- `email_dispatches`
- `email_dispatch_recipients`
- `email_unsubscribes`

Requisitos:

- envio por worker.
- unsubscribe.
- bounce/complaint tracking.
- idempotencia por destinatario.
- rate limit por tenant.
- templates versionados.

Gate:

- envio em lote sem travar API.
- reenvio nao duplica email para quem ja recebeu.
- unsubscribe bloqueia envio futuro.

### F11 - Sales foundation

Objetivo: migrar a parte de vendas sem depender do OmniiaPro.

Dominios:

- contatos
- inbox
- campanhas
- bots
- webchat
- WhatsApp/Telegram/Discord/canais de venda

Mesmas regras:

- tenant-scoped.
- actor por membership.
- jobs para webhooks e mensagens.
- rate limit por canal.
- audit log.

Gate:

- contatos funcionais.
- inbox funcional.
- webhooks entram por fila.
- frontend Labby chama apenas backend Labby.

### F12 - Cutover 100%

Objetivo: desligar dependencia Labby -> OmniiaPro.

Passos:

1. Deploy do backend Labby.
2. Migrations em producao.
3. DNS `api.labby.com.br`.
4. Configurar envs.
5. Frontend aponta para backend novo.
6. Teste E2E.
7. Monitoramento ativo.
8. Bloquear uso de `/api/v2/omniaflow/*` para Labby.
9. Remover codigo Labby antigo do OmniiaPro quando seguro.

Gate:

- login real.
- convite real.
- permissao por modulo.
- social media basico.
- digest real.
- sales basico.
- nenhuma chamada do frontend para OmniiaPro.

## Modelo de banco: regras obrigatorias daqui para frente

Toda tabela de dominio deve ter:

- `id`
- `tenant_id`
- timestamps
- indices por `tenant_id`
- constraints/unique tenant-scoped quando houver external id

Tabelas que representam acao humana devem ter:

- `created_by_membership_id`
- `updated_by_membership_id` quando fizer sentido

Tabelas que integram provider externo devem ter:

- `provider`
- `external_id`
- unique por `tenant_id + provider + external_id`
- payload bruto ou metadata JSONB quando necessario

Tabelas de jobs devem ter:

- `idempotency_key`
- `status`
- `attempts`
- `run_after`
- `locked_at`

## Backend: regras obrigatorias

- Request HTTP nao executa processo pesado.
- Toda acao pesada cria job.
- Todo job tem idempotencia.
- Todo provider tem adapter separado.
- Toda integracao externa tem timeout.
- Todo retry tem backoff.
- Todo erro persistente vira dead-letter ou status final.
- Toda query de lista tem pagination.
- Todo endpoint tenant-scoped valida membership ativa.
- Admin so age dentro dos modulos aos quais tem acesso, exceto owner.

## Observabilidade obrigatoria antes de producao real

Metricas:

- request latency por endpoint
- error rate
- DB pool usage
- Redis latency
- fila por queue
- jobs pendentes
- jobs falhos
- tempo medio de processamento
- chamadas por provider
- rate limit hit por tenant/provider

Logs:

- `tenant_id`
- `membership_id`
- `request_id`
- `job_id`
- `provider`
- `external_id`

Alertas:

- fila parada
- muitos jobs falhando
- token de provider expirando sem refresh
- DB perto do limite de conexoes
- webhook com aumento de erro
- envio de email com bounce/complaint alto

## Load test antes do cutover

Cenarios minimos:

- 500 usuarios autenticados.
- 50 tenants.
- login/refresh concorrente.
- listagem de equipe/modulos.
- criacao/aceite de convites.
- webhooks duplicados.
- jobs simultaneos de social ingestion.
- digest em lote.
- publicacao agendada com retry.

Metas iniciais:

- API responde rapido para requests simples.
- jobs pesados nao afetam login/equipe.
- sem N+1 em listagens.
- sem duplicidade em retry.
- sem vazamento entre tenants.

## Riscos principais

1. Redes sociais tem rate limits diferentes e mudam politica.
2. Tokens externos precisam ser criptografados e renovados com seguranca.
3. Webhooks podem chegar duplicados, fora de ordem ou em pico.
4. IA pode ser cara e lenta, entao precisa de limite por tenant.
5. Email em massa precisa de unsubscribe, bounce e complaint.
6. Sem jobs/outbox, retries podem duplicar publicacoes ou emails.
7. Sem observabilidade, gargalos de fila ficam invisiveis.
8. Sem load test, 500 usuarios podem mascarar problema que so aparece em jobs.

## Perguntas para Claude revisar

1. O plano de fases esta na ordem correta para uma Labby social-heavy?
2. A fundacao de jobs/outbox deve vir imediatamente antes de qualquer provider real?
3. O modelo `social_accounts + tokens + sync states + webhook events` cobre Facebook,
   Instagram, YouTube, LinkedIn e X?
4. Falta alguma tabela essencial antes das integracoes sociais?
5. A estrategia de idempotencia proposta e suficiente para webhooks, publish e email?
6. O plano de filas separadas por tipo de workload esta adequado?
7. A ausencia de Docker muda alguma recomendacao de deploy?
8. Para 500+ usuarios, quais indices adicionais ele recomenda antes dos modulos
   Social/Sales completos?
9. Ele recomenda Postgres RLS ou filtro por `tenant_id` na aplicacao neste momento?
10. Que gates ele exigiria antes de apontar `api.labby.com.br` para o backend novo?
