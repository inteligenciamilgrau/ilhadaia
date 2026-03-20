# Game State and Simulation Logic - BBBia

Atualizado em: 2026-03-18

## Visao geral

Este documento descreve como o estado do mundo evolui por tick, como os modos alteram a simulacao e quais campos principais sao enviados para frontend/API.

## Mundo e grid

O mundo usa grid dinamico por `game_mode`:

- `survival`: 32x32
- `gincana`: 32x32
- `warfare`: 40x40
- `economy`: 36x36
- `gangwar`: 40x40
- `hybrid`: 44x44

Landmarks (casas, lago e cemiterio) sao calculados em funcao de `world.size`.

## Estrutura base de entidades

Entidades sao armazenadas em `world.entities` (mapa `id -> objeto`).

Tipos base recorrentes:

- `agent`
- `tree`, `stone`, `water`
- `house`, `cemetery`
- itens e objetos por modo (`checkpoint`, `control_zone`, `market_post`, `black_market`, etc.)

## Vitals e ciclo de vida de agentes

Campos principais por agente:

- `hp`, `hunger`, `thirst`
- `is_alive`, `is_zombie`
- `profile_id`
- `tokens_used`, `token_budget`
- dados sociais/missao conforme feature

Eventos de morte e zumbi continuam no loop base, com regras de dia/noite e seguranca por abrigo.

## Ciclo por tick (ordem simplificada)

1. Atualiza relogio da simulacao (`ticks`).
2. Processa spawn pendente e interacoes automaticas.
3. Executa decisoes de IA dos agentes elegiveis.
4. Aplica regras base (vitals, dia/noite, miasma, etc.).
5. Executa engines ativas por modo:
   - `gincana`: checkpoints/artefato/timer
   - `warfare`: faccoes/territorio/roles/combate
   - `economy`: mercado/craft/contratos
   - `gangwar` (`gangwar` e `hybrid`): depots/sabotagem/black market
6. Gera eventos e transmite estado via WebSocket.

## Estado retornado por `world.get_state()`

Campos globais relevantes:

- `ticks`, `started`, `game_over`, `winner`
- `size`, `game_mode`
- `agents`, `entities`, `scores`
- blocos por modo:
  - `gincana` quando `game_mode == gincana`
  - `warfare` quando `game_mode == warfare`
  - `economy` sempre exposto
  - `gangwar` quando `game_mode in (gangwar, hybrid)`

## Features e impacto no estado

### F01/F03/F05 (comando, inspector, admin)

- Comando humano em agente (`human_command`, expiracao).
- Leitura de decisoes e memoria relevante por agente.
- Mutacoes admin (spawn, patch de mundo, troca de perfil).

### F04/F07/F08 (eventos, reputacao, missoes)

- Evento ativo com janela temporal e historico.
- Aliancas e traicoes alterando reputacao.
- Catalogo/progresso de missoes por agente.

### F12 (gincana)

- placar por agente
- dono de checkpoint
- estado do artefato e entregas
- timer e vencedor

### F13..F16 (warfare)

- faccao por agente
- role tatico por agente
- zona de territorio e holder
- placar por faccao
- eventos de throw/combat

### F10/F17/F18/F19 (economia)

- moedas por agente
- receitas de crafting
- precos e estoque de mercado
- contratos abertos/cumpridos
- reputacao comercial

### F20 (gangwar/hybrid)

- gangue por agente
- score por gangue
- estado dos depots e lock por sabotagem
- black market (precos/estoque)

## Passo a passo para validar estado por modo

### Survival

1. `POST /reset` com `game_mode=survival`.
2. `GET /system/info` e `GET /agents/all`.
3. Observar `update` no WebSocket.

### Gincana

1. `POST /reset` com `game_mode=gincana`.
2. `POST /modes/gincana/start`.
3. `GET /gincana/state` e acompanhar `events`.

### Warfare

1. `POST /reset` com `game_mode=warfare`.
2. `POST /modes/warfare/start`.
3. `GET /warfare/state`, `/warfare/territory`, `/teams/{team}/roles`.

### Economy

1. `POST /reset` com `game_mode=economy`.
2. `POST /modes/economy/start`.
3. `GET /economy/state`, `/market/prices`, `/contracts`.

### Gangwar/Hybrid

1. `POST /reset` com `game_mode=gangwar` ou `hybrid`.
2. `POST /gangwar/start` (ou `/modes/hybrid/start`).
3. `GET /gangwar/state` (ou `/modes/hybrid/state`).

## Referencias

- `docs/API_REFERENCE.md`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT_GUIDE.md`
