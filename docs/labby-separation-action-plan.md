# Labby - Plano de Acao Revisado para Separacao 100%

Data: 2026-06-01
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

- `6fd4760 docs: add revised Labby separation action plan`
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

Este plano foi reordenado apos revisao externa. A prioridade nao e construir a
plataforma social multi-rede completa agora. A prioridade e separar a Labby do
OmniiaPro cedo, com o fluxo existente funcionando no backend proprio. A expansao
para Facebook, Instagram, YouTube e LinkedIn entra depois do cutover.

### G0 - Repo e governanca imediata

Status: pendente por decisao operacional.

Falta:

- Criar repo GitHub `labby-backend`.
- Configurar `origin`.
- Fazer push da branch atual.
- Ativar CI no GitHub.
- Proteger branch principal.
- Documentar secrets de producao.

Gate:

- Historico local protegido no GitHub.
- CI rodando no repo remoto.
- Branch principal protegida.

## Trilho A - Separacao primeiro

Objetivo: tirar a Labby do risco de acoplamento com OmniiaPro antes de expandir
produto.

### A0 - Base ja entregue

Status: feito localmente.

Inclui:

- F1 bootstrap tecnico.
- F2 auth/memberships.
- F3 equipe/permissoes.
- hardening de escala inicial.
- remocao de Docker do fluxo.

Gate ja validado localmente:

- `ruff` passou.
- `pytest` passou.
- Alembic gera SQL.
- endpoints atuais sem N+1 relevante.

### A1 - Jobs/outbox para o fluxo existente

Status: fundacao tecnica iniciada localmente.

Objetivo: criar a fundacao de processos pesados antes de transplantar Social e
Sales.

Decisao importante a fechar: Celery continua sendo executor dos jobs, mas o banco
vira fonte de verdade do estado/idempotencia. Redis/Celery transporta execucao;
tabelas `jobs/outbox/webhook_events` guardam historico, retry e auditoria. Nao
devem existir duas filas concorrentes sem contrato.

Criar tabelas:

- `jobs`
- `job_attempts`
- `outbox_events`
- `webhook_events`
- `rate_limit_events` ou equivalente auditavel

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
- todo webhook bruto e persistido antes de processar.

Gate:

- Criar job idempotente.
- Worker processa a partir do job.
- Retry funciona.
- Job duplicado nao duplica efeito.
- Metricas basicas de fila existem.
- Teste cross-tenant cobrindo jobs e eventos.

Entregue localmente em 2026-06-01:

- Migration `003_jobs_outbox_foundation`.
- Tabelas `jobs`, `job_attempts`, `outbox_events`, `webhook_events` e
  `rate_limit_events`.
- `JobQueueService` com enqueue idempotente, claim com `FOR UPDATE SKIP LOCKED`,
  retry/backoff, dead-letter e metricas por tenant.
- Runner Celery `labby.jobs.dispatch_due_jobs`.
- Endpoint admin `GET /api/v2/labby/jobs/metrics`.

### A2 - Social atual transplantado

Objetivo: portar o fluxo que ja existe hoje antes de criar a plataforma social
multi-rede.

Fluxo alvo:

- X/news radar.
- IA cria/rewrite noticia.
- curadoria/aprovacao.
- digest por email.
- subscribers/unsubscribe.
- dispatch com Resend.

Regras:

- podar smells do codigo antigo durante o transplante.
- manter contrato que o frontend atual ja usa quando possivel.
- trocar acoplamentos OmniiaFlow/OmniiaPro por dominios Labby.
- jobs para captura, IA e envio.
- idempotencia para run, item de curadoria e dispatch.

Gate:

- Radar do X funcionando no backend Labby.
- IA funcionando por job.
- Digest real enviado.
- Unsubscribe funcionando.
- Nenhuma chamada do frontend social para OmniiaPro.
- Teste E2E do fluxo X -> IA -> digest.

### A3 - Sales transplantado

Objetivo: portar o minimo de Sales necessario para a Labby operar sem OmniiaPro.

Ordem:

1. Contacts primeiro.
2. Inbox.
3. Campanhas.
4. Bots.
5. Webchat.
6. Webhooks existentes: Evolution, WhatsApp Cloud, Telegram, Discord.

Regras:

- tenant-scoped.
- actor por `membership_id`.
- webhooks entram por `webhook_events` e jobs.
- rate limit por canal.
- audit log em acoes criticas.

Gate:

- Contacts funcional.
- Primeiro canal/webhook funcional via fila.
- Frontend Sales chamando backend Labby.
- Teste E2E basico de Sales sem OmniiaPro.

### A4 - Integracoes reais standalone

Objetivo: remover dependencias indiretas do OmniiaPro nos servicos externos.

Integracoes:

- Resend.
- X API.
- provedor IA.
- eventuais secrets/configs de canais de venda.

Regras:

- secrets `LABBY_*`.
- timeouts em toda chamada externa.
- retries controlados por job.
- logs com `tenant_id`, `job_id`, `provider`.

Gate:

- Nenhuma config de Labby depende de env OmniiaPro.
- Falha externa nao quebra request principal.
- Jobs registram erro e retry.

### A5 - Observabilidade e load test

Objetivo: validar a separacao antes do cutover.

Metricas obrigatorias:

- request latency por endpoint.
- error rate.
- DB pool usage.
- Redis latency.
- fila por queue.
- jobs pendentes.
- jobs falhos.
- chamadas por provider.
- rate limit por tenant/provider.

Load test minimo:

- 500 usuarios autenticados.
- 50 tenants.
- login/refresh concorrente.
- equipe/modulos.
- convites.
- X/news capture.
- IA por job.
- digest em lote.
- webhooks duplicados.

Gate:

- API simples continua responsiva durante jobs.
- Sem duplicidade em retry.
- Sem vazamento cross-tenant.
- Sem N+1 nas listagens principais.
- Limite de conexoes DB dimensionado.

### A6 - Cutover Labby 100%

Objetivo: apontar `api.labby.com.br` para o backend Labby e tirar o frontend da
dependencia do OmniiaPro.

Passos:

1. Deploy do backend Labby.
2. Migrations em producao.
3. Configurar envs reais.
4. Configurar DNS `api.labby.com.br`.
5. Apontar frontend para backend novo.
6. Rodar E2E.
7. Monitorar filas, requests, DB e Redis.

Gate:

- login real.
- convite real.
- permissao por modulo.
- Social atual funcionando.
- Sales minimo funcionando.
- digest real.
- nenhuma chamada do frontend para `/api/v2/omniaflow/*`.

### A7 - Descomissionar OmniiaFlow no OmniiaPro

Objetivo: reduzir risco no produto principal.

Passos:

- bloquear rotas antigas usadas pela Labby.
- remover jobs antigos de OmniiaFlow.
- remover envs antigos quando seguro.
- manter backup/migration notes.

Gate:

- Labby opera sem OmniiaPro.
- OmniiaPro continua com testes verdes.
- Nenhuma dependencia cruzada ativa.

## Trilho B - Plataforma social multi-rede depois do cutover

Objetivo: expandir a Labby para social media parruda sem atrasar a separacao.

Este trilho so comeca depois do A6, exceto por decisoes de schema que sejam
baratas e nao bloqueiem a separacao.

### B1 - Fundacao de integracoes sociais multi-rede

Objetivo: criar base unica para Facebook, Instagram, YouTube, LinkedIn, X e
futuras redes.

Criar tabelas:

- `social_providers`
- `social_oauth_grants`
- `social_accounts`
- `social_account_tokens`
- `social_scopes`
- `social_webhook_subscriptions`
- `social_sync_states`
- `social_external_objects`

Decisao importante: separar grant OAuth de conta social. No Meta, por exemplo,
um token/grant pode dar acesso a N paginas/contas. Entao:

- `social_oauth_grants` representa a autorizacao/token.
- `social_accounts` representa paginas, perfis, canais ou contas conectadas.

Requisitos:

- criptografia de tokens externos.
- refresh automatico antes de expirar.
- revogacao/desconexao segura.
- validacao de scopes por funcionalidade.
- rate limit por provider, tenant, grant e conta.

Gate:

- conectar provider fake.
- salvar grant criptografado.
- mapear N contas a partir de um grant.
- renovar token.
- desconectar conta.
- bloquear acao sem scope correto.

### B2 - Webhooks sociais + fallback de polling

Objetivo: receber eventos quando a rede suporta webhook e usar polling quando
nao suporta ou quando o webhook nao cobre tudo.

Fluxo webhook:

1. endpoint publico recebe evento.
2. valida assinatura/verificacao.
3. persiste evento bruto em `webhook_events`.
4. retorna rapido.
5. worker processa.

Fluxo polling:

1. scheduler cria job de sync.
2. adapter busca incrementos por cursor.
3. persiste objetos com idempotencia.
4. atualiza `social_sync_states`.

Gate:

- webhook duplicado nao duplica processamento.
- webhook invalido e rejeitado.
- polling incremental funciona.
- provider sem webhook ainda sincroniza.

### B3 - Social ingestion multi-rede

Objetivo: capturar posts, comentarios, replies, metricas, mencoes, midias e
mensagens quando a API permitir.

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
- separar conteudo bruto de conteudo processado pela IA.
- retry sem duplicar dados.

Gate:

- sync incremental.
- deduplicacao.
- paginacao/cursor por provider.
- captura de metricas por job.

### B4 - Publishing, calendario e reconciliacao

Objetivo: publicar e agendar conteudo sem risco de double-post.

Tabelas provaveis:

- `social_publication_plans`
- `social_scheduled_posts`
- `social_publish_attempts`
- `social_post_variants`
- `social_publish_reconciliations`

Requisitos:

- idempotencia por publicacao.
- status de publicacao.
- tentativa por provider.
- preview antes de publicar.
- reconciliacao depois de publicar para confirmar external id.
- retry nao pode gerar double-post.
- logs de erro por provider.

Gate:

- criar post agendado.
- worker publica.
- reconciliacao confirma external id.
- erro gera retry/backoff seguro.
- publicacao duplicada e bloqueada.

### B5 - IA e curadoria social multi-rede

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

### B6 - Digest/newsletter evoluido

Objetivo: evoluir digest para listas, campanhas e audiencias robustas.

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
- reenvio nao duplica email.
- unsubscribe bloqueia envio futuro.

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

1. O novo Trilho A prioriza corretamente separar o fluxo existente antes de
   expandir para multi-rede?
2. A1 deve usar Celery como executor e tabelas `jobs/outbox/webhook_events` como
   fonte de verdade, ou ha uma alternativa melhor sem criar duas filas?
3. Para transplantar o Social atual, quais smells do fluxo X -> IA -> digest
   devem ser removidos obrigatoriamente antes do cutover?
4. Para transplantar Sales, a ordem contacts -> inbox -> campanhas/bots/webchat
   -> webhooks esta correta?
5. O gate de A6 e suficiente para declarar separacao 100% da Labby?
6. O descomissionamento A7 protege bem o OmniiaPro depois do cutover?
7. No Trilho B, separar `social_oauth_grants` de `social_accounts` cobre bem Meta,
   YouTube, LinkedIn e X?
8. O fallback de polling deve ser modelado ja em B2 para todas as redes, mesmo as
   que possuem webhook?
9. A reconciliacao de publish proposta em B4 e suficiente para evitar double-post?
10. Ele recomenda filtro por `tenant_id` na aplicacao agora + testes cross-tenant,
    deixando Postgres RLS como hardening antes do launch?
