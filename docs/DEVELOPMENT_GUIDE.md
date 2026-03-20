# Development Guide - BBBia

Atualizado em: 2026-03-18

## Objetivo deste guia

Este guia mostra como subir o ambiente local, validar o backend e usar as funcionalidades novas (F01..F20) em passo a passo.

## Pre-requisitos

- Python 3.12+
- `pip`
- endpoint OpenAI-compatible (OmniRoute ou equivalente)

## Setup local

```bash
git clone https://github.com/inteligenciamilgrau/ilhadaia.git
cd ilhadaia/backend
pip install -r requirements.txt
cp ../.env.example .env
```

Edite `backend/.env` com pelo menos:

```env
ADMIN_TOKEN=troque-este-token
OMNIROUTER_URL=http://localhost:20128/v1
OMNIROUTER_API_KEY=omniroute-local
ALLOWED_ORIGINS=*
```

Aliases aceitos para compatibilidade:

- URL: `OMNIROUTER_URL`, `OMNIROUTE_URL`, `OPENAI_BASE_URL`
- API key: `OMNIROUTER_API_KEY`, `OMNIROUTE_API_KEY`, `OPENAI_API_KEY`

## Subindo o backend

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

Verificacao rapida:

```bash
curl -s http://localhost:8001/ | jq
```

## Frontend oficial

Com o backend no ar, abra:

- `http://localhost:8001/frontend/index.html`
- `http://localhost:8001/frontend/dashboard.html`
- `http://localhost:8001/frontend/models.html`

## Operacao via UI (passo a passo - Feature Ops)

Objetivo: operar os contratos F01..F20 diretamente pela interface, sem curl manual.

1. Abra `http://localhost:8001/frontend/models.html`.
2. Clique na aba `Feature Ops`.
3. Bloco A (`F01..F09`):
   - use `Definir comando`, `Decisoes`, `Memoria relevante` para F01/F03
   - use `Spawn admin`, `Patch world`, `Admin profile` para F05
   - use `Rodar AB`, `Temporadas`, `Versao de perfil`, `Eventos`, `Missoes`, `Alianca`
4. Bloco B (`F12..F16`):
   - `Reset modo` para `gincana`/`warfare`
   - `Start gincana/warfare`, `Throw`, `Roles`, `Zona`
5. Bloco C (`F10/F11/F17..F20`):
   - `Start economy`, `Recipes`, `Craft/Build`, `Market`, `Contracts`
   - `Start gangwar/hybrid`, `Webhook register/test/deliveries/stats`
6. Valide cada chamada no painel `Resultado Feature Ops`.
7. Se aparecer `401`, informe token admin no modal e repita a acao.

## Passo a passo geral de operacao

### 1) Reiniciar sessao no modo desejado

```bash
export API=http://localhost:8001
export ADMIN_TOKEN=troque-este-token

curl -s -X POST "$API/reset" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"player_count":4,"game_mode":"survival"}' | jq
```

Valores validos de `game_mode`: `survival`, `gincana`, `warfare`, `economy`, `gangwar`, `hybrid`.

### 2) Descobrir IDs de agentes

```bash
curl -s "$API/agents/all" | jq '.agents[] | {id,name,profile_id}'
```

### 3) F01 - comando humano

```bash
AGENT_ID=<id>

curl -s -X POST "$API/agents/$AGENT_ID/command" \
  -H "Content-Type: application/json" \
  -d '{"command":"colete madeira e volte para casa","expire_ticks":40}' | jq

curl -s "$API/agents/$AGENT_ID/command" | jq

curl -s -X POST "$API/agents/$AGENT_ID/command/cancel" | jq
```

### 4) F03 - inspector

```bash
curl -s "$API/agents/$AGENT_ID/decisions?n=5" | jq
curl -s "$API/agents/$AGENT_ID/memory/relevant" | jq
```

### 5) F05 - admin console

```bash
curl -s -X POST "$API/admin/spawn" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":"supply_crate","x":10,"y":10,"extra":{}}' | jq

curl -s -X POST "$API/admin/world/patch" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_chance":0.01}' | jq

curl -s -X POST "$API/admin/agent/$AGENT_ID/profile" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profile_id":"claude-haiku"}' | jq
```

### 6) F04, F07, F08 - eventos, reputacao e missoes

```bash
curl -s "$API/events/templates" | jq
curl -s -X POST "$API/events/trigger" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"tempestade"}' | jq

curl -s -X POST "$API/missions/assign" -H "X-Admin-Token: $ADMIN_TOKEN" | jq
curl -s "$API/missions/progress" | jq
```

Alianca (exemplo com dois agentes):

```bash
AGENT_A=<id_a>
AGENT_B=<id_b>

curl -s -X POST "$API/agents/$AGENT_A/alliances" \
  -H "Content-Type: application/json" \
  -d "{\"target_agent_id\":\"$AGENT_B\"}" | jq

curl -s -X POST "$API/agents/$AGENT_A/betray" | jq
```

### 7) F12 - gincana

```bash
curl -s -X POST "$API/reset" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"player_count":4,"game_mode":"gincana"}' | jq

curl -s -X POST "$API/modes/gincana/start" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_ticks":400}' | jq

curl -s "$API/modes/gincana/templates" | jq
curl -s "$API/gincana/state" | jq
```

### 8) F13..F16 - warfare

```bash
curl -s -X POST "$API/reset" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"player_count":6,"game_mode":"warfare"}' | jq

curl -s -X POST "$API/modes/warfare/start" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_ticks":600}' | jq

curl -s "$API/modes/warfare/state" | jq
curl -s "$API/combat/config" | jq
curl -s "$API/teams/alpha/roles" | jq
curl -s "$API/zones/state" | jq
```

Arremesso:

```bash
curl -s -X POST "$API/actions/throw" \
  -H "Content-Type: application/json" \
  -d '{"attacker_id":"<id>","target_x":12,"target_y":12}' | jq
```

### 9) F10, F17, F18, F19 - economia

```bash
curl -s -X POST "$API/reset" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"player_count":4,"game_mode":"economy"}' | jq

curl -s -X POST "$API/modes/economy/start" \
  -H "X-Admin-Token: $ADMIN_TOKEN" | jq

curl -s "$API/economy/state" | jq
curl -s "$API/recipes" | jq
curl -s "$API/market/prices" | jq
```

Craft/build/mercado/contrato:

```bash
curl -s -X POST "$API/craft" -H "Content-Type: application/json" \
  -d '{"agent_id":"<id>","recipe":"bandage"}' | jq

curl -s -X POST "$API/build" -H "Content-Type: application/json" \
  -d '{"agent_id":"<id>","structure_type":"wall","x":8,"y":8}' | jq

curl -s -X POST "$API/market/buy" -H "Content-Type: application/json" \
  -d '{"agent_id":"<id>","item":"apple","qty":1}' | jq

curl -s -X POST "$API/contracts" -H "Content-Type: application/json" \
  -d '{"requester_id":"<id>","item":"wood","qty":2,"reward":8.0}' | jq
```

### 10) F20 - gangwar e hybrid

```bash
curl -s -X POST "$API/reset" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"player_count":6,"game_mode":"gangwar"}' | jq

curl -s -X POST "$API/gangwar/start" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_ticks":500}' | jq

curl -s "$API/gangwar/state" | jq
curl -s "$API/gangwar/black-market/prices" | jq
```

No modo `hybrid`, use aliases:

- `POST /modes/hybrid/start`
- `GET /modes/hybrid/state`
- `POST /modes/hybrid/stop`

### 11) F06 e F02 - temporadas, ELO, AB

```bash
curl -s -X POST "$API/seasons" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"S1","game_mode":"survival","description":"temporada local"}' | jq

curl -s "$API/seasons" | jq

curl -s -X POST "$API/benchmarks/ab" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profile_a":"claude-kiro","profile_b":"kimi-thinking","game_mode":"survival","ticks":200}' | jq
```

### 12) F11 - webhooks

Registro:

```bash
curl -s -X POST "$API/webhooks" \
  -H "Content-Type: application/json" \
  -d '{
    "owner_id":"dev-local",
    "url":"https://webhook.site/SEU-ID",
    "events":["all"],
    "secret":"segredo"
  }' | jq
```

Teste e analitico (admin):

```bash
curl -s -X POST "$API/webhooks/test" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"owner_id":"dev-local"}' | jq

curl -s "$API/webhooks/deliveries" -H "X-Admin-Token: $ADMIN_TOKEN" | jq
curl -s "$API/webhooks/admin/stats" -H "X-Admin-Token: $ADMIN_TOKEN" | jq
curl -s "$API/webhooks/admin/event-types" | jq
```

## Testes

```bash
cd backend
pytest -q
```

Resultado de referencia nesta atualizacao: `200 passed, 1 skipped`.

## Limpeza de estado local

```bash
find backend/data -type f -delete
find backend/logs -type f -delete
find backend -maxdepth 1 \( -name 'hall_of_fame.json' -o -name 'world_settings.json' \) -delete
```

## Documentos complementares

- `docs/API_REFERENCE.md`
- `docs/ARCHITECTURE.md`
- `docs/GAME_STATE.md`
- `docs/features/IMPLEMENTATION_STATUS_2026-03-18.md`
- `docs/features/FRONTEND_QA_CHECKLIST_2026-03-18.md`
