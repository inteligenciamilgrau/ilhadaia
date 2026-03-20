# API Reference - BBBia

Atualizado em: 2026-03-18

Base URL: `http://localhost:8001`

Autenticacao de admin: header `X-Admin-Token: <ADMIN_TOKEN>` (valor definido em `.env: ADMIN_TOKEN`)

> **Importante:** `POST /reset` **tambem exige** `X-Admin-Token`. Nao e um endpoint publico.
> Todos os endpoints marcados com `(admin)` abaixo e os de controle de sessao (`/reset`) exigem o header.

## Convencoes

- Endpoints marcados com `(admin)` exigem token.
- Alguns recursos possuem rotas alias para compatibilidade com contratos de feature.
- Quando houver alias, o comportamento funcional e o payload sao equivalentes.

## Quickstart de uso (passo a passo)

Prerequisitos:

- backend ativo em `http://localhost:8001`
- header admin quando necessario: `X-Admin-Token: <ADMIN_TOKEN>`

Sequencia recomendada:

1. Criar sessao/mode:
   - `POST /reset` com `player_count` e `game_mode`
2. Obter agentes:
   - `GET /agents/all`
3. Operar pela UI (recomendado):
   - `frontend/admin.html` → painel gerencial com **8 abas** cobrindo F01-F20 (requer ADMIN_TOKEN)
     - Cole o token no campo superior direito; ele salva automaticamente em `localStorage`
     - Se o campo estiver vazio, ele fica vermelho e o foco vai para ele automaticamente
   - `frontend/models.html` → aba `Feature Ops` (cobertura funcional dos contratos F01..F20)
4. Executar fluxo de feature desejado:
   - F01/F03/F05: `command`, `decisions/memory`, `admin/*`
   - F12: reset `gincana` + `POST /modes/gincana/start`
   - F13..F16: reset `warfare` + `POST /modes/warfare/start`
   - F10/F17/F18/F19: reset `economy` + `POST /modes/economy/start`
   - F20: reset `gangwar`/`hybrid` + `POST /gangwar/start` (ou alias hybrid)
5. Acompanhar estado:
   - REST: endpoints `/state` por dominio
   - tempo real: WebSocket `/ws`
6. Exportar e auditar:
   - `/sessions/{id}/export`, `/sessions/{id}/decisions/export`, `/webhooks/admin/*`

## Status e sistema

- `GET /`
- `GET /system/info`
- `GET /rate-limit/status`

## Configuracao de IA e catalogo de modelos

- `GET /settings/ai`
- `POST /settings/ai`
- `POST /settings/ai_interval`
- `GET /models`
- `GET /profiles`
- `POST /profiles/add` (admin)
- `POST /debug/test_model`

## Agentes

- `POST /agents/register` (admin)
- `GET /agents/all`
- `GET /agents/{agent_id}/state`
- `DELETE /agent/{agent_id}` (admin)

## Modo Comandante e Inspector

F01:
- `POST /agents/{agent_id}/command`
- `POST /agents/{agent_id}/command/cancel`
- `GET /agents/{agent_id}/command`

F03:
- `GET /agents/{agent_id}/decisions`
- `GET /agents/{agent_id}/memory/relevant`

## Console Admin (F05)

- `POST /admin/spawn` (admin)
- `POST /admin/event` (admin)
- `POST /admin/world/patch` (admin)
- `POST /admin/agent/profile` (admin)
- `POST /admin/agent/{agent_id}/profile` (admin, alias)
- `GET /admin/world/state` (admin)

## Sessoes, replay e exports

- `GET /sessions`
- `GET /sessions/{session_id}/replay`
- `GET /sessions/{session_id}/replay/frame/{tick}`
- `GET /sessions/{session_id}/export`
- `GET /sessions/{session_id}/decisions/export`
- `GET /world/scoreboard`
- `GET /world/scoreboard/export`

## Torneios

- `POST /tournaments` (admin)
- `POST /tournaments/{t_id}/join`
- `POST /tournaments/{t_id}/start` (admin)
- `GET /tournaments`
- `GET /tournaments/{tournament_id}/status`
- `GET /tournaments/{tournament_id}/leaderboard`

## Temporadas, ELO e benchmark A/B

F06:
- `POST /seasons` (admin)
- `GET /seasons`
- `POST /seasons/{season_id}/end` (admin)
- `GET /seasons/{season_id}/leaderboard`
- `POST /seasons/{season_id}/record` (admin)
- `GET /elo/{profile_id}`

F02:
- `POST /benchmarks/ab` (admin)
- `GET /benchmarks/ab/{run_id}`
- `GET /benchmarks/ab/{run_id}/report`
- `POST /ab/compare` (admin, legado)
- `GET /ab/results` (legado)
- `GET /ab/stats` (legado)

F09:
- `POST /profiles/{profile_id}/versions` (admin)
- `GET /profiles/{profile_id}/versions`
- `GET /profiles/versions/all`
- `POST /profiles/{profile_id}/activate/{version}` (admin)
- `POST /profiles/{profile_id}/versions/{version}/rollback` (admin, alias legado)

## Eventos dinamicos, reputacao e missoes

F04:
- `GET /events/active`
- `GET /events/history`
- `POST /events/trigger` (admin)
- `GET /events/templates`
- `GET /events/types` (alias)

F07:
- `POST /agents/{agent_id}/alliances`
- `POST /agents/{agent_id}/alliance` (alias)
- `DELETE /agents/{agent_id}/alliance`
- `POST /agents/{agent_id}/betray`
- `GET /agents/{agent_id}/reputation`

F08:
- `GET /missions/templates`
- `GET /missions/catalog` (alias)
- `POST /missions/assign` (admin)
- `GET /agents/{agent_id}/mission`
- `GET /missions/progress`

## Modos de jogo - Gincana, Warfare, Economia, Hybrid/GangWar

F12 (Gincana):
- `POST /modes/gincana/start` (admin)
- `GET /modes/gincana/templates`
- `POST /gincana/start` (admin, alias)
- `POST /gincana/stop` (admin)
- `GET /gincana/state`
- `GET /gincana/templates` (alias)

F13/F14/F15/F16 (Warfare e subfeatures):
- `POST /modes/warfare/start` (admin)
- `GET /modes/warfare/state`
- `POST /warfare/start` (admin, alias)
- `POST /warfare/stop` (admin)
- `GET /warfare/state` (alias)
- `POST /actions/throw`
- `POST /warfare/throw` (alias)
- `GET /combat/config`
- `GET /warfare/roles`
- `GET /warfare/territory`
- `POST /teams/{team_id}/roles`
- `GET /teams/{team_id}/roles`
- `POST /zones/config`
- `GET /zones/state`

F17/F10/F18/F19 (Economia, crafting, mercado, contratos):
- `POST /modes/economy/start` (admin)
- `GET /modes/economy/state`
- `POST /economy/start` (admin, alias)
- `GET /economy/state` (alias)
- `GET /recipes`
- `GET /economy/recipes` (alias)
- `POST /craft`
- `POST /economy/craft` (alias)
- `POST /build`
- `POST /economy/build` (alias)
- `POST /economy/trade`
- `GET /economy/coins`
- `GET /economy/market`
- `GET /market/prices`
- `POST /market/recalculate`
- `POST /market/buy`
- `POST /economy/market/buy` (alias)
- `POST /market/sell`
- `POST /economy/market/sell` (alias)
- `GET /contracts`
- `GET /economy/contracts` (alias)
- `POST /contracts`
- `POST /economy/contracts` (alias)
- `POST /contracts/{contract_id}/fulfill`
- `POST /economy/contracts/fulfill` (alias)
- `GET /economy/reputation`
- `GET /agents/{agent_id}/wallet`

F20 (GangWar / Hybrid):
- `POST /gangwar/start` (admin)
- `POST /gangwar/stop` (admin)
- `GET /gangwar/state`
- `POST /gangwar/sabotage`
- `POST /gangwar/depot/deposit`
- `POST /gangwar/depot/withdraw`
- `GET /gangwar/depot/{gang}`
- `POST /gangwar/black-market/buy`
- `GET /gangwar/black-market/prices`
- `POST /modes/hybrid/start` (admin)
- `POST /modes/hybrid/stop` (admin)
- `GET /modes/hybrid/state`

## Webhooks (F11)

Operacionais:
- `POST /webhooks`
- `POST /webhooks/register` (alias)
- `GET /webhooks/{owner_id}`
- `DELETE /webhooks/{webhook_id}` (query: `owner_id`)
- `POST /webhooks/test/{owner_id}` (admin)
- `POST /webhooks/test` (admin, payload com `owner_id`)
- `GET /webhooks/deliveries` (admin)

Admin analytics:
- `GET /webhooks/admin/history` (admin)
- `GET /webhooks/admin/stats` (admin)
- `GET /webhooks/admin/event-types`

## Memoria persistente

- `GET /memories`
- `POST /memories/save/{agent_id}`
- `DELETE /memories/{owner_id}/{agent_name}` (admin)

## API remota legada (agente externo)

- `POST /join`
- `GET /agent/{agent_id}/context`
- `POST /agent/{agent_id}/action`

## WebSocket

- `ws://localhost:8001/ws`

Mensagens:
- `init`
- `update`
- `reset`
