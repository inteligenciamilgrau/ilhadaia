# Arquitetura do Sistema - BBBia

Atualizado em: 2026-03-18

## Resumo

O BBBia roda com backend FastAPI (single worker), loop de simulacao em `World`, engines de modo (`GincanaEngine`, `WarfareEngine`, `EconomyEngine`, `GangWarEngine`), persistencia SQLite WAL e frontend web em **quatro telas** (`index.html`, `dashboard.html`, `models.html`, `admin.html`).

Estado tecnico confirmado nesta data:

- Testes backend: `200 passed, 1 skipped`
- Contratos de endpoints das features F01..F20: cobertos no backend
- Cobertura de contratos das features no frontend oficial: `48/48` (aba `Feature Ops`)
- Referencia oficial de endpoints: `docs/API_REFERENCE.md`

## Topologia atual

```text
Frontend (index/dashboard/models/admin)
  | HTTP REST + WebSocket /ws
  v
FastAPI (backend/main.py)
  |- World (loop de ticks + regras base)
  |- Thinker (orquestracao de decisoes IA)
  |- Engines de modo
  |   |- GincanaEngine (F12)
  |   |- WarfareEngine (F13..F16)
  |   |- EconomyEngine (F10, F17..F19)
  |   |- GangWarEngine (F20)
  |- Stores (session/replay/decision/memory/webhook)
  v
SQLite WAL + arquivos NDJSON de log/replay
```

## Camadas e responsabilidades

### API e orquestracao (`backend/main.py`)

- Exposicao de endpoints REST e WebSocket.
- Validacao de auth admin por `X-Admin-Token`.
- Controle de sessao ativa e reset por `game_mode`.
- Broadcast de estado para clientes conectados.

### Simulacao (`backend/world.py`)

- Grid dinamico com tamanhos por modo:
  - `survival`: 32
  - `gincana`: 32
  - `warfare`: 40
  - `economy`: 36
  - `gangwar`: 40
  - `hybrid`: 44
- Regras base: ticks, entidades, vitais, ciclo dia/noite, spawn por modo.
- Integracao com engines especializadas.

### Runtime de IA (`backend/runtime/*`)

- `thinker.py`: decide acoes com base no contexto do mundo.
- `profiles.py`: catalogo de perfis e roteamento OpenAI-compatible.
- `memory.py` e `relevance.py`: memoria e recuperacao de contexto.
- Engines de gameplay por feature/mode.

### Persistencia (`backend/storage/*`)

- `session_store.py`: sessoes, scoreboard, temporadas, ELO, AB results.
- `decision_log.py`: log NDJSON de decisoes por sessao.
- `replay_store.py`: snapshots de replay.
- `memory_store.py`: memoria persistente por agente.
- `webhook_manager.py`: cadastro/disparo/retry/historico de webhooks.

## Modos de jogo e features

| Modo | Engine principal | Features ligadas |
|---|---|---|
| `survival` | World (base) | F01, F03, F04, F05, F06, F07, F08, F09 |
| `gincana` | `GincanaEngine` | F12 |
| `warfare` | `WarfareEngine` | F13, F14, F15, F16 |
| `economy` | `EconomyEngine` | F10, F17, F18, F19 |
| `gangwar` | `GangWarEngine` | F20 |
| `hybrid` | `GangWarEngine` + economia integrada | F20 (aliases `/modes/hybrid/*`) |

## Fluxo tecnico de uma decisao

```text
tick -> World escolhe agentes elegiveis
     -> Thinker monta contexto (estado + memoria relevante)
     -> adapter OpenAI-compatible chama modelo do profile_id
     -> resposta validada em schema de acao
     -> World aplica acao
     -> decision_log + benchmark + replay atualizados
     -> broadcast via WebSocket para frontend
```

## Fluxo tecnico de uma sessao (passo a passo)

1. Cliente chama `POST /reset` com `player_count` e `game_mode`.
2. Backend cria nova sessao em `session_store`.
3. `World` inicializa mapa e objetos do modo.
4. Frontend conecta em `ws://localhost:8001/ws`.
5. Cada tick atualiza estado e envia mensagens `update`.
6. Endpoints de feature alteram o estado em tempo real (ex.: `/modes/warfare/start`, `/contracts`, `/gangwar/sabotage`).
7. Ao finalizar ciclo, logs/replays/scoreboard permanecem persistidos para analise e export.

## Observabilidade e qualidade

- Endpoints de health e informacao: `/`, `/system/info`, `/rate-limit/status`.
- Export e analitico: sessions/replay/scoreboard/decision export.
- Webhooks F11 com historico e stats admin:
  - `/webhooks/admin/history`
  - `/webhooks/admin/stats`
  - `/webhooks/admin/event-types`

## Frontend (quatro telas)

| Tela | Arquivo | Funcao |
|------|---------|--------|
| Ilha | `frontend/index.html` | Observer 3D, chat, replay, WebSocket |
| Dashboard | `frontend/dashboard.html` | Metricas, graficos, scoreboard, exportacao |
| Modelos | `frontend/models.html` | Perfis, teste de modelos, Feature Ops |
| **Admin** | `frontend/admin.html` | **Painel gerencial completo** (8 abas, F01-F20) |

### admin.html — Abas e Features

| Aba | Features cobertas |
|-----|------------------|
| Mundo | Reset, patch, spawn, eventos admin, sessoes |
| Agentes | Lista ao vivo, F01, F03, F07, troca de perfil |
| Modos | Seletor visual de game_mode |
| Warfare | F12-F16: gincana, warfare, throw, roles, territorio |
| Economia | F10/F17-F20: craft, trade, mercado, contratos, gangwar |
| Webhooks | F11: registro, teste, entregas, stats |
| Benchmark | F02/F06/F09: A/B, temporadas, ELO, versoes |
| Avancado | Torneios, F04, F08, memorias, rate limit |

## Limites atuais da arquitetura

- Processo unico (single worker) para API + loop + broadcast.
- Sem barramento externo para fanout horizontal de WebSocket.
- QA funcional frontend desktop/mobile ainda pendente de execucao formal.

## Referencias

- `docs/API_REFERENCE.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/GAME_STATE.md`
- `docs/features/IMPLEMENTATION_STATUS_2026-03-18.md`
- `docs/features/CHECKLIST.md`
