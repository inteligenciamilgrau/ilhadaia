# Plano de Features - BBBia

Atualizado em: 2026-03-18

## Estado atual

As features F01..F20 estao implementadas no backend e organizadas por fase em `docs/features/`.

Evidencias de fechamento tecnico:

- Testes backend: `200 passed, 1 skipped`
- Contratos docs x backend: cobertos
- Cobertura de contratos no frontend oficial: `48/48` (via `frontend/models.html`, aba `Feature Ops`)
- Status consolidado: `docs/features/IMPLEMENTATION_STATUS_2026-03-18.md`

## Mapa de fases

| Fase | Features | Estado |
|---|---|---|
| Fase 1 | F01, F03, F05 | Concluida |
| Fase 2 | F02, F06, F09 | Concluida |
| Fase 3 | F04, F07, F08 | Concluida |
| Fase 4 | F12 | Concluida |
| Fase 5 | F13, F14, F15, F16 | Concluida |
| Fase 6 | F10, F17, F18, F19 | Concluida |
| Fase 7 | F20 | Concluida |
| Fase 8 | F11 | Concluida |

## Documentacao por feature

Fonte principal para requisitos e contratos:

- `docs/features/INDEX.md`
- `docs/features/F01_MODE_COMMANDER.md` ... `docs/features/F20_GANG_WAR_HYBRID.md`
- `docs/features/CHECKLIST.md`

## Passo a passo UI oficial (Feature Ops)

1. Abrir `http://localhost:8001/frontend/models.html`.
2. Ir para a aba `Feature Ops`.
3. Usar `Bloco A` para `F01..F09`.
4. Usar `Bloco B` para `F12..F16`.
5. Usar `Bloco C` para `F10/F11/F17..F20`.
6. Confirmar resultado de cada chamada no painel `Resultado Feature Ops`.

## Como usar as funcionalidades novas (passo a passo por bloco)

## Bloco A - comando, inspector e admin (F01/F03/F05)

1. Reinicie em `survival` com `POST /reset`.
2. Escolha agente em `GET /agents/all`.
3. Envie comando em `POST /agents/{id}/command`.
4. Inspecione com `GET /agents/{id}/decisions` e `GET /agents/{id}/memory/relevant`.
5. Execute intervencao admin (`/admin/spawn`, `/admin/world/patch`, `/admin/agent/{id}/profile`).

## Bloco B - benchmark, temporadas e perfis (F02/F06/F09)

1. Crie temporada: `POST /seasons`.
2. Rode comparacao AB: `POST /benchmarks/ab`.
3. Consulte resultado: `GET /benchmarks/ab/{run_id}` e `/report`.
4. Versione perfil: `POST /profiles/{id}/versions`.
5. Ative versao: `POST /profiles/{id}/activate/{version}`.

## Bloco C - eventos, reputacao e missoes (F04/F07/F08)

1. Consulte templates: `GET /events/templates`.
2. Dispare evento: `POST /events/trigger` (admin).
3. Crie alianca: `POST /agents/{id}/alliances`.
4. Quebre alianca: `POST /agents/{id}/betray`.
5. Atribua missoes: `POST /missions/assign` (admin).
6. Acompanhe progresso: `GET /missions/progress`.

## Bloco D - gincana (F12)

1. `POST /reset` com `game_mode=gincana`.
2. `POST /modes/gincana/start`.
3. `GET /gincana/state` durante a partida.
4. `POST /gincana/stop` para encerrar.

## Bloco E - warfare (F13..F16)

1. `POST /reset` com `game_mode=warfare`.
2. `POST /modes/warfare/start`.
3. Use combate: `POST /actions/throw`.
4. Gerencie papeis: `POST/GET /teams/{id}/roles`.
5. Consulte territorio: `GET /zones/state`.

## Bloco F - economia e contratos (F10/F17/F18/F19)

1. `POST /reset` com `game_mode=economy`.
2. `POST /modes/economy/start`.
3. Craft/build: `POST /craft`, `POST /build`.
4. Mercado: `GET /market/prices`, `POST /market/buy`, `POST /market/sell`.
5. Contratos: `POST /contracts`, `POST /contracts/{id}/fulfill`, `GET /contracts`.

## Bloco G - gangwar/hybrid (F20)

1. `POST /reset` com `game_mode=gangwar` ou `hybrid`.
2. `POST /gangwar/start` (ou `POST /modes/hybrid/start`).
3. Execute sabotagem/deposito/black market.
4. Consulte estado: `GET /gangwar/state` (ou alias hybrid).

## Bloco H - webhooks (F11)

1. Registre webhook: `POST /webhooks`.
2. Dispare teste: `POST /webhooks/test` (admin).
3. Consulte entregas: `GET /webhooks/deliveries`.
4. Consulte stats/history/event-types admin.

## O que ainda falta para 100%

Com backend + contratos de frontend fechados, os pontos abaixo seguem em aberto:

1. Rodar QA manual desktop/mobile com evidencia.
2. Consolidar observabilidade por feature no dashboard/admin.

Referencias:

- `docs/features/FRONTEND_ENDPOINT_COVERAGE_2026-03-18.md`
- `docs/features/FRONTEND_QA_CHECKLIST_2026-03-18.md`

## Diretriz para novas evolucoes

Qualquer nova feature deve seguir este ciclo:

1. especificar em `docs/features/Fxx_*.md`
2. implementar backend + testes
3. documentar contratos na API reference
4. integrar frontend
5. validar QA desktop/mobile
6. atualizar checklist/status
