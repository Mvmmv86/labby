# A2 - Checklist de contrato com frontend

Data: 2026-06-01

Fonte comparada: `C:\Users\marcu\omniaflow-app\src\lib\news.ts`.

## Segmentos, fontes e curador

Rotas compativeis:

- `GET /api/v2/labby/social/news/segments`
- `GET /api/v2/labby/social/news/segments/{segment_id}`
- `POST /api/v2/labby/social/news/segments`
- `POST /api/v2/labby/social/news/segments/from-seed`
- `PATCH /api/v2/labby/social/news/segments/{segment_id}`
- `DELETE /api/v2/labby/social/news/segments/{segment_id}`
- `GET /api/v2/labby/social/news/segments/{segment_id}/sources`
- `POST /api/v2/labby/social/news/segments/{segment_id}/sources`
- `DELETE /api/v2/labby/social/news/sources/{source_id}`
- `GET /api/v2/labby/social/news/segments/{segment_id}/curator`
- `PUT /api/v2/labby/social/news/segments/{segment_id}/curator`

Campos legados preservados para a UI:

- `nome`
- `descricao`
- `base_conhecimento`
- `tipos_evento`
- `vocabulario`
- `ativo`
- `valor`
- `origem`
- `modelo`
- `temperatura`
- `system_prompt_complementar`

## Runs, schedules e subscribers

Rotas compativeis:

- `POST /api/v2/labby/social/news/runs/manual`
- `GET /api/v2/labby/social/news/runs`
- `GET /api/v2/labby/social/news/runs/{run_id}`
- `GET /api/v2/labby/social/news/runs/{run_id}/items`
- `GET /api/v2/labby/social/news/segments/{segment_id}/schedules`
- `POST /api/v2/labby/social/news/segments/{segment_id}/schedules/recalibrate`
- `PATCH /api/v2/labby/social/news/schedules/{schedule_id}`
- `DELETE /api/v2/labby/social/news/schedules/{schedule_id}`
- `GET /api/v2/labby/social/news/subscribers`
- `POST /api/v2/labby/social/news/subscribers`
- `POST /api/v2/labby/social/news/subscribers/import-csv`
- `PATCH /api/v2/labby/social/news/subscribers/{subscriber_id}`
- `DELETE /api/v2/labby/social/news/subscribers/{subscriber_id}`
- `GET /api/v2/labby/social/news/unsubscribe/{token}`
- `POST /api/v2/labby/social/news/unsubscribe/{token}`

Status de runs traduzidos para o contrato legado:

- `queued`/`capturing` -> `capturando`
- `curation_stage1` -> `curadoria_stage1`
- `rewriting` -> `reescrevendo`
- `curation_stage2` -> `curadoria_stage2`
- `sending` -> `enviando`
- `succeeded` -> `concluida`
- `failed` -> `erro`
- `cancelled` -> `cancelada`

## Curadoria

Rotas compativeis:

- `GET /api/v2/labby/social/news/curation/stage1`
- `GET /api/v2/labby/social/news/curation/stage2`
- `GET /api/v2/labby/social/news/curation/ready`
- `GET /api/v2/labby/social/news/curation/dispatch-config`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/stage1`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/rewrite`
- `POST /api/v2/labby/social/news/curation/items/{item_id}/stage2`
- `POST /api/v2/labby/social/news/curation/runs/{run_id}/dispatch`
- `GET /api/v2/labby/social/news/curation/dispatches`

Campos de item preservados para a UI:

- `autor_handle`
- `autor_nome`
- `conteudo_original`
- `conteudo_reescrito`
- `reescrito_modelo`
- `reescrito_at`
- `rejeitado_motivo`
- `aprovado_stage1_por`
- `aprovado_stage1_at`
- `aprovado_stage2_por`
- `aprovado_stage2_at`
- `ranking_motivo`
- `ranking_origem`
- `tipo_match`

Status traduzidos para o contrato legado:

- `ranked` -> `ranqueado`
- `approved_stage1` -> `aprovado_stage1`
- `rejected_stage1` -> `rejeitado_stage1`
- `rewritten` -> `reescrito`
- `approved_stage2` -> `aprovado_stage2`
- `rejected_stage2` -> `rejeitado_stage2`
- `sent` -> `enviado`

## Dispatch

`POST /curation/runs/{run_id}/dispatch` preserva o formato esperado pela UI:

- `run_id`
- `sent`
- `failed`
- `skipped`
- `subscribers`
- `items`

`GET /curation/dispatches` preserva:

- `email`
- `resend_id`
- `status`
- `error_message`
- `sent_at`

## Teste

Cobertura local:

- `test_frontend_social_parity_routes_are_available`
- `test_frontend_curation_e2e_contract_from_stage1_to_dispatch`
- `test_get_item_rejects_cross_tenant_row`

Esse teste valida o fluxo de contrato stage 1 -> rewrite -> stage 2 -> ready ->
dispatch usando as mesmas rotas e os mesmos nomes de campos que o frontend
atual consome.
