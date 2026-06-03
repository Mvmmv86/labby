# Labby - Plano de Acao Revisado para Separacao 100%

Data: 2026-06-01
Branch local: `feature/f3-team-invites-modules`
Repo local: `C:\Users\marcu\labby-backend`
Repo GitHub: `git@github.com:Mvmmv86/labby.git`

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

- `d4abb36 feat: complete social news frontend parity`
- `62650a1 feat: add social news curation flow`
- `33b62ba fix: harden social news curation cutover parity`
- `9cdcbcb docs: record social curation flow`
- `ad7f5ad feat: add social news job handlers`
- `afaa63c feat: add social news foundation`
- `a9897d0 fix: configure package discovery for CI`
- `a550fbf docs: update GitHub repository status`
- `6fd4760 docs: add revised Labby separation action plan`
- `79c9422 feat: add jobs outbox foundation`
- `1065034 chore: add scalability database foundation`
- `a897d73 chore: remove Docker from Labby backend flow`
- `85c8aa0 feat: add team invites and module permissions`
- `22eb4e0 feat: add Labby auth membership foundation`
- `8fcdffc fix: harden F1 bootstrap review findings`
- `ebc4151 chore: add identity foundation migration`
- `1ef7a74 chore: bootstrap Labby backend`

Remote GitHub configurado em `git@github.com:Mvmmv86/labby.git`.
Branches publicadas:

- `main`
- `feature/f3-team-invites-modules`

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

Status: parcialmente feito.

Feito:

- Criar repo GitHub `Mvmmv86/labby`.
- Configurar `origin` via SSH.
- Fazer push da branch atual.
- Criar/publicar branch principal `main`.
- Ativar CI no GitHub.
- CI verde em `main` e `feature/f3-team-invites-modules`.

Falta:

- Proteger branch principal.

Entregue localmente em 2026-06-01:

- Documento `docs/production-secrets.md`.

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
- Ajuste das migrations iniciais para gerar UUID no Postgres via
  `gen_random_uuid()`, necessario para inserts por SQL bruto.
- Reaper de jobs presos em `running`, configuravel por
  `LABBY_JOB_RUNNING_TIMEOUT_SECONDS` e `LABBY_JOB_REAPER_BATCH_SIZE`.

### A2 - Social atual transplantado

Status: fluxo tecnico principal iniciado localmente.

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

Entregue localmente em 2026-06-01:

- Migrations `004_social_news_foundation` e `005_social_news_schedules`.
- Tabelas `social_news_segments`, `social_news_sources`,
  `social_news_curators`, `social_news_runs`, `social_news_items`,
  `social_news_subscribers`, `social_news_subscriber_consent_events` e
  `social_news_dispatches`.
- Tabela `social_news_schedules`.
- Endpoints `/api/v2/labby/social/news/*`, incluindo aliases
  `/api/v2/labby/social/news/curation/*` compativeis com o frontend atual.
- Paridade do frontend para segmentos, seed `crypto_v1`, sources, curator,
  schedules, runs manuais/listagem/detalhe, subscribers flat/import CSV e
  unsubscribe GET/POST.
- Aliases de curadoria devolvem nomes de campos e status esperados pelo
  frontend legado (`autor_handle`, `conteudo_original`, `ranqueado`,
  `reescrito`, `aprovado_stage2`).
- Runs, rewrite e dispatch criam jobs idempotentes no A1.
- Handlers dos jobs `social.news.capture`, `social.news.rewrite` e
  `social.news.dispatch` registrados no worker.
- Adapter X standalone para TwitterAPI.io com secrets `LABBY_*`.
- Captura X por worker com dedupe, ranking por engagement e persistencia em
  `social_news_items`.
- Curadoria operacional com listagem de itens e aprovar/rejeitar stage 1/stage 2.
- Aprovacao stage 1 enfileira rewrite idempotente em `worker-ai` na mesma
  transacao da mudanca de status.
- Rewrite tenta IA standalone via OpenAI quando configurada por `LABBY_AI_*`,
  com fallback editorial seguro.
- Rewrite idempotente no worker para evitar double-cost em retry/reaper.
- Custo de IA calculado por tokens quando `LABBY_AI_*_COST_PER_MILLION_TOKENS`
  esta configurado.
- Dispatch Resend por worker com `social_news_dispatches`.
- Subscribers com unsubscribe assinado e hash persistido.
- Teste de paridade das rotas sociais chamadas pelo frontend atual.
- Teste cross-tenant negativo explicito para item tenant-scoped.
- Teste E2E de contrato frontend cobrindo stage 1, rewrite, stage 2, ready e
  dispatch.
- Documento `docs/a2-social-current-handoff.md`.

### A3 - Sales transplantado

Status: fatias Contacts, Inbox, Channels/Webhook Evolution e Analytics iniciadas
localmente.

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

Entregue localmente em 2026-06-01:

- Migration `006_sales_contacts_foundation`.
- Tabela `sales_contacts`.
- Endpoints flat `/api/v2/labby/contacts/*` compativeis com o frontend atual.
- Endpoints canonicos `/api/v2/labby/sales/contacts/*`.
- CRUD de contacts com listagem paginada e filtros `search`, `grupo` e `tag`.
- Batch import em `POST /contacts/batch` e `/sales/contacts/batch`.
- Batch import com `INSERT ... ON CONFLICT`, idempotente no banco e tolerante a
  falha parcial por linha.
- `require_module("sales")` no router.
- Actor por `created_by_membership_id` e `updated_by_membership_id`.
- Unique parcial por `tenant_id + phone_normalized`.
- Normalizacao de telefone/email.
- Testes de contrato flat/canonico, modulo `sales`, idempotencia de batch,
  cross-tenant negativo no service e integracao real com Postgres no CI.
- Documento `docs/a3-sales-contacts-handoff.md`.

Entregue localmente em 2026-06-02:

- Migration `007_sales_inbox_foundation`.
- Tabelas `sales_channels`, `sales_contact_channels`, `sales_conversations` e
  `sales_messages`.
- Endpoints flat `/api/v2/labby/conversations/*` compativeis com o frontend
  atual.
- Endpoints canonicos `/api/v2/labby/sales/conversations/*`.
- Listagem de Inbox com filtros `channel_tipo`, `status`, `search`,
  `atendente_id`, paginacao e agregacao em lote de ultima mensagem e nao-lidas.
- Resumo de notificacoes `conversations/notifications/summary`.
- Detalhe de conversa, listagem cursor-based de mensagens, `mark-read`,
  `close` e envio interno de mensagem de saida com status `pending`.
- Contacts agora retorna `total_conversas`, `canais_vinculados`,
  `canais` e `conversas_recentes` usando agregacoes em lote, sem voltar aos
  subqueries por linha do OmniiaFlow antigo.
- `auth/me` e auth responses retornam `canais_conectados` e `canais` a partir
  de `sales_channels`, para o frontend habilitar o Inbox quando houver canal.
- `require_module("sales")` no router de conversas.
- Actor humano por `membership_id` em `assigned_to_membership_id`,
  `sender_membership_id`, `created_by_membership_id` e
  `updated_by_membership_id`.
- Unique parcial por `tenant_id + provider + external_id` em mensagens para
  dedupe de webhooks/providers.
- Testes de contrato flat/canonico, modulo `sales`, agregacoes de Inbox,
  cursor/mark-read/send/close, dedupe de mensagem externa e cross-tenant real
  com Postgres no CI.
- Documento `docs/a3-sales-inbox-handoff.md`.

Entregue localmente em 2026-06-02, fatia Channels/Webhook Evolution/Analytics:

- CRUD de canais em `/api/v2/labby/channels/*` e
  `/api/v2/labby/sales/channels/*`.
- Canais suportados no contrato:
  - `whatsapp_evolution`
  - `whatsapp_cloud`
  - `telegram`
  - `discord`
  - `web_chatbot`
- Respostas de channels redigem campos sensiveis de `config` e nao expoem
  `webhook_secret`.
- Mutations de channels exigem modulo `sales` e role `owner/admin`.
- Integracao standalone de canais em `app/integrations/sales_channels.py`,
  usando `LABBY_*`.
- Connect real habilitado nesta fatia para `whatsapp_evolution` e
  `web_chatbot`; `telegram`, `discord` e `whatsapp_cloud` aguardam receivers
  inbound e retornam `501` ao conectar.
- Settings:
  - `LABBY_PUBLIC_API_BASE_URL`
  - `LABBY_EVOLUTION_API_URL`
  - `LABBY_EVOLUTION_API_KEY`
  - `LABBY_EVOLUTION_API_TIMEOUT_SECONDS`
- Webhook publico `POST /api/v2/labby/webhooks/evolution/{channel_id}`.
- Webhook Evolution valida segredo por comparacao constante.
- Evento bruto e job `sales.webhook.evolution` gravados na mesma transacao via
  `webhook_events` e `jobs`.
- Webhook Evolution persiste mensagem recebida como `ignored`, sem criar job,
  quando o canal nao esta `conectado`.
- Handler do job Evolution cria/atualiza contato, vinculo de canal, conversa e
  mensagem.
- Dedupe de webhook/mensagem por idempotencia do evento e por
  `tenant_id + provider + external_id`.
- Analytics do dashboard em `/api/v2/labby/analytics/*` e
  `/api/v2/labby/sales/analytics/*`:
  - dashboard
  - messages
  - activity
- `campanhas_ativas` retorna `0` ate a migration de campanhas entrar.
- Testes de contrato flat/canonico para channels e analytics.
- Teste de webhook publico Evolution.
- Teste de integracao Postgres para webhook Evolution duplicado sem duplicar
  mensagem.
- Teste de webhook Evolution em canal desconectado sem criar job/mensagem.
- Teste de connect bloqueado para provider sem inbound.
- Documento `docs/a3-sales-channels-webhooks-analytics-handoff.md`.

Entregue localmente em 2026-06-02, fatia Campaigns:

- Migration `008_sales_campaigns_foundation`.
- Tabelas `sales_campaigns` e `sales_campaign_recipients`.
- Endpoints flat `/api/v2/labby/campaigns/*` e canonicos
  `/api/v2/labby/sales/campaigns/*`.
- CRUD de campanhas, recipients por contatos, preview de recipients, start,
  cancel, listagem de recipients e dispatch.
- Recipients derivados de contatos ativos e sem `optout`, com dedupe por
  `tenant_id + campaign_id + contact_id`.
- Targeting por filtros `filtro_tags`/`filtro_grupo` ainda nao foi transplantado;
  esta fatia adiciona recipients por `contact_ids`/`contatos_ids`.
- `start` ativa a campanha; dispatch HTTP exige campanha ativa e cria job
  idempotente `sales.campaign.dispatch` na fila `worker-sales-campaigns`.
- Worker de campaigns cria mensagens de saida com status `pending` e provider
  `labby_campaign`, sem depender ainda de envio externo real.
- Reprocessamento do mesmo job nao duplica mensagem, conversa nem contadores.
- OpenAPI regenerado em `contracts/labby-openapi.yaml`.
- Testes de contrato flat/canonico, metadata, dispatch idempotente,
  cross-tenant real e regressao de lifecycle webhook Evolution.
- Documento `docs/a3-sales-campaigns-handoff.md`.

Entregue localmente em 2026-06-03, fatia Bots/Widget publico:

- Migration `009_sales_bots_widget_foundation`.
- Tabelas `sales_bots` e `sales_bot_runs`.
- Indice unico parcial para `sales_channels` de Web Chat por `widget_id`,
  evitando ambiguidade publica entre tenants.
- Endpoints flat `/api/v2/labby/bots/*` e canonicos
  `/api/v2/labby/sales/bots/*`.
- CRUD de bots, toggle e duplicate.
- Campos legados preservados para o frontend: `nome`, `ativo`,
  `tipo_trigger`, `trigger_valor`, `channel_ids`, `total_acionamentos`,
  `total_concluidos` e `total_transferidos`.
- Mutations de bot exigem modulo `sales` e role `owner/admin/agent`.
- Widget publico em:
  - `GET /widget/{widget_id}/loader.js`
  - `GET /widget/{widget_id}/config`
  - `POST /widget/{widget_id}/messages`
  - `GET /widget/{widget_id}/messages`
- Widget resolve `tenant_id`/`channel_id` pelo `widget_id`, sem confiar no
  payload publico.
- Widget exige canal `web_chatbot` conectado/ativo.
- `allowed_origins` em `sales_channels.config` e respeitado quando configurado.
- Rate limit auditavel para envio/polling via `rate_limit_events`.
- Mensagens do widget usam provider `web_widget` e external id deterministico,
  com `ON CONFLICT DO NOTHING`.
- Reentrega da mesma mensagem do widget nao duplica contato, conversa,
  mensagem, contador ou resposta de bot.
- Runtime minimo de bot no widget com trigger, FAQ, welcome/fallback e
  transferencia para humano, sem chamada externa longa no request publico.
- OpenAPI regenerado em `contracts/labby-openapi.yaml`.
- Testes de contrato flat/canonico para bots, contrato publico do widget,
  metadata, widget idempotente, bot runtime e cross-tenant real no CI.
- Documento `docs/a3-sales-bots-widget-handoff.md`.

Ainda falta em A3:

- Webhooks Telegram, WhatsApp Cloud e Discord.
- Outbound dispatch real de mensagens `pending`.
- Bot com LLM real por job/adapter standalone, se entrar no MVP de producao.
- Rate limit consolidado por canal/provider para webhooks publicos.
- Audit log de mutations criticas.

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
