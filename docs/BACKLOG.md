# Backlog - BBBia

Atualizado em: 2026-03-18

## Pendencias prioritarias

### B02 - QA funcional desktop/mobile com evidencia

- Status: aberto
- Contexto: checklist de QA existe, mas ainda nao foi executado de ponta a ponta.
- Evidencia: `docs/features/FRONTEND_QA_CHECKLIST_2026-03-18.md`.
- Resultado esperado: checklist preenchido com data, viewport e observacao/screenshot por item.

### B03 - Observabilidade por feature no dashboard/admin

- Status: em andamento
- Contexto: metricas e visoes por feature ainda parciais.
- Resultado esperado: paines por bloco funcional (comandos, modos, economia, webhooks) com indicadores de sucesso/erro.

### B04 - Modularizacao de `backend/main.py`

- Status: aberto
- Contexto: arquivo central concentra muitas responsabilidades (rotas + orquestracao + integracoes).
- Resultado esperado: separar por dominio (`api/routes_*`, servicos, ws manager) para reduzir acoplamento.

### B05 - Escalabilidade de broadcast (multi-worker)

- Status: aberto
- Contexto: arquitetura atual depende de processo unico para loop + WebSocket broadcast.
- Resultado esperado: barramento pub/sub externo (ex.: Redis) para horizontalizar workers.

## Itens de monitoramento

- Providers OpenAI-compatible sujeitos a rate limits/erro de credencial por conta.
- Crescimento de memoria persistida em sessoes longas (politica de TTL ainda a evoluir).

## Itens concluidos que sairam do backlog

- Implementacao backend de features F01..F20.
- Contratos de endpoints das features alinhados no backend.
- Integracao de frontend dos contratos F01..F20.
- API reference atualizada com aliases e dominios atuais.
- Testes backend verdes na rodada de fechamento (`200 passed, 1 skipped`).
