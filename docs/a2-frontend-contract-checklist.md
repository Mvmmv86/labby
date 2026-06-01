# A2 - Checklist de contrato com frontend

Data: 2026-06-01

Fonte comparada: `C:\Users\marcu\omniaflow-app\src\lib\news.ts`.

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

- `test_frontend_curation_e2e_contract_from_stage1_to_dispatch`

Esse teste valida o fluxo de contrato stage 1 -> rewrite -> stage 2 -> ready ->
dispatch usando as mesmas rotas e os mesmos nomes de campos que o frontend
atual consome.
