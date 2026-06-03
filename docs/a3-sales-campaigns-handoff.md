# A3 Sales Campaigns - Handoff

Data: 2026-06-02
Branch: `feature/f3-team-invites-modules`

## Escopo entregue

Fatia de Campaigns depois de Contacts, Inbox e Channels/Webhook Evolution.

Inclui:

- Migration `008_sales_campaigns_foundation`.
- Tabelas `sales_campaigns` e `sales_campaign_recipients`.
- Router `app/api/v2/labby/sales_campaigns.py`.
- Service `app/domains/sales/campaign_service.py`.
- Handler de job `sales.campaign.dispatch` em
  `app/domains/sales/campaign_jobs.py`.
- OpenAPI regenerado em `contracts/labby-openapi.yaml`.

## Rotas

Campaigns flat e canonico:

- `GET /api/v2/labby/campaigns/`
- `POST /api/v2/labby/campaigns/`
- `GET /api/v2/labby/campaigns/{campaign_id}`
- `PUT /api/v2/labby/campaigns/{campaign_id}`
- `DELETE /api/v2/labby/campaigns/{campaign_id}`
- `GET /api/v2/labby/campaigns/{campaign_id}/recipients`
- `POST /api/v2/labby/campaigns/{campaign_id}/recipients`
- `POST /api/v2/labby/campaigns/{campaign_id}/preview-recipients`
- `POST /api/v2/labby/campaigns/{campaign_id}/start`
- `POST /api/v2/labby/campaigns/{campaign_id}/dispatch`
- `POST /api/v2/labby/campaigns/{campaign_id}/cancel`
- mesmas rotas em `/api/v2/labby/sales/campaigns/*`

## Decisoes

- Campaigns sao tenant-scoped e exigem modulo `sales`.
- Mutations exigem role `owner`, `admin` ou `agent`, seguindo Contacts/Inbox.
- Recipients sao derivados de `sales_contacts` ativos e sem `optout`.
- Insercao de recipients usa `INSERT ... SELECT ... ON CONFLICT DO NOTHING`,
  com unique parcial por `tenant_id + campaign_id + contact_id`.
- `start` muda a campanha para `ativa`. O `dispatch` exige campanha ativa,
  marca como `sending` e cria job idempotente `sales.campaign.dispatch`.
- `PUT` nao aceita alteracao direta de `status`; transicoes de estado ficam
  restritas a `start`, `dispatch` e `cancel`. Para manter paridade com o
  modal legado do frontend, o schema publico de update ignora extras como
  `media_url`, `filtro_tags`, `filtro_grupo` e `contatos_ids`.
- O worker cria mensagens de saida com status `pending`, provider
  `labby_campaign` e enfileira `sales.message.dispatch`. O envio externo real
  via Evolution foi entregue na fatia de outbound.
- Dedupe do worker usa `sales_messages(tenant_id, provider, external_id)`.
- Reprocessar o mesmo job nao duplica mensagens, conversas ou side effects de
  contador.

## Pontos anti-regressao

- Re-dispatch da mesma campanha retorna o mesmo job por idempotency key.
- Reprocessamento do job depois de recipients `queued` retorna `skipped`.
- Contato com `optout` nao entra como recipient.
- Campanha de outro tenant retorna `404`.
- Evento lifecycle `connection.update` do Evolution continua enfileirando mesmo
  com canal ainda nao conectado.

## Testes adicionados

- `tests/test_sales_campaign_routes.py`
  - contrato flat/canonico;
  - `require_module("sales")`;
  - recipients, preview, start, dispatch e cancel.
- `tests/test_sales_campaigns_integration.py`
  - handler registrado;
  - recipients com dedupe e optout;
  - dispatch idempotente sem duplicar jobs;
  - worker idempotente sem duplicar mensagens;
  - isolamento cross-tenant real.
- `tests/test_sales_models.py`
  - metadata das tabelas;
  - unique de campaigns por idempotency key;
  - unique de recipients por campanha+contato.
- `tests/test_sales_webhooks_integration.py`
  - regressao do lifecycle `connection.update`.

## Validacao local

- `ruff check .`
- `pytest -q` -> `103 passed, 4 skipped`
- `python -c "import yaml; yaml.safe_load(open('contracts/labby-openapi.yaml', encoding='utf-8')); print('openapi ok')"`

Os testes de integracao Postgres rodam no CI quando `LABBY_TEST_DATABASE_URL`
esta configurado. Localmente ficam pulados se a env nao existir.

## Fora desta fatia

- Outbound real para providers alem de Evolution.
- Scheduler de campanhas `scheduled`.
- Targeting por `filtro_tags` e `filtro_grupo`. Nesta fatia, recipients sao
  adicionados por `contact_ids`/`contatos_ids`.
- Rate limit para providers futuros.
- Audit log de mutations criticas.
- Relatorio detalhado de bounces/entregas por provider.
