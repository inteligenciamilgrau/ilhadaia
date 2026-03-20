# BBBia: A Ilha da IA

BBBia é um simulador de sobrevivência social com benchmark de modelos de IA. O backend FastAPI executa o mundo, expõe REST + WebSocket e serve **quatro interfaces web**:

- `frontend/index.html`: observer 3D da ilha em tempo real
- `frontend/dashboard.html`: dashboard analítico de sessões, score e exportações
- `frontend/models.html`: console para testar perfis, cadastrar agentes e inspecionar o runtime
- `frontend/admin.html`: **painel gerencial completo** — cobre todas as features F01-F20 (8 abas: mundo, agentes, modos, warfare, economia, webhooks, benchmark e avançado)

## Modos de Jogo

| Modo | Tamanho do Mapa | Funcionalidades |
|------|----------------|-----------------|
| `survival` | 32×32 | Modo padrão — recursos, zumbis, ciclo dia/noite |
| `gincana` | 32×32 | F12 — Checkpoints, artefato, placar por equipe, timer |
| `warfare` | 40×40 | F13-F16 — Facções, arremesso, papéis táticos, território |
| `economy` | 36×36 | F10/F17-F19 — Crafting, trade P2P, mercado dinâmico, contratos |
| `gangwar` | 40×40 | F20 — Gangues, black market, sabotagem, supply posts |
| `hybrid` | 44×44 | Expansão futura |

## Engines de Runtime

| Engine | Arquivo | Features |
|--------|---------|---------|
| `GincanaEngine` | `runtime/gincana_engine.py` | F12: checkpoints, artefato, placar, timer |
| `WarfareEngine` | `runtime/warfare_engine.py` | F13-F16: facções, throw_stone AOE, scout/medic/warrior, território |
| `EconomyEngine` | `runtime/economy_engine.py` | F10/F17-F19: 5 receitas crafting, trade, mercado, contratos |
| `GangWarEngine` | `runtime/gangwar_engine.py` | F20: gangues, depósito, sabotagem, black market volátil |

## Stack

- **Backend:** FastAPI + asyncio + WebSocket
- **Runtime IA:** `runtime/thinker.py` + adapters Gemini/OpenAI-compatible
- **Persistência:** SQLite WAL + NDJSON de decisões e replay
- **Frontend:** páginas estáticas em HTML/CSS/JS servidas por `StaticFiles`
- **Testes:** 174 testes automatizados (`pytest backend/tests/test_engine.py`)
- **Ambiente:** Python 3.12+

## Setup Rápido

```bash
# 1. clone
git clone https://github.com/inteligenciamilgrau/ilhadaia.git
cd ilhadaia

# 2. instale as dependências do backend
cd backend
pip install -r requirements.txt

# 3. configure o ambiente local
cp ../.env.example .env
# edite os valores necessários

# 4. suba o backend
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

O comando deve ser executado a partir de `backend/`. Com isso, os paths relativos de `data/` e `logs/` ficam dentro de `backend/`, como esperado pelo projeto.

## Variáveis de Ambiente

```env
ADMIN_TOKEN=troque-este-token
AUTHORIZED_IDS=777
OMNIROUTER_URL=http://192.168.0.15:20128/v1
OMNIROUTER_API_KEY=omniroute-local
ALLOWED_ORIGINS=*

# Opcional — credenciais externas diretas
GEMINI_API_KEY=sua_chave_gemini_aqui
```

- `POST /agents/register` usa `claude-kiro` como default quando `profile_id` não é enviado.
- Os quatro NPCs iniciais da ilha usam: `claude-kiro`, `kimi-thinking`, `kimi-groq`, `claude-haiku`.
- O backend também aceita `OMNIROUTE_API_KEY` e `OPENAI_BASE_URL`/`OPENAI_API_KEY` como aliases.

> **`POST /reset` exige `X-Admin-Token`** — não é um endpoint público. Sem o header, retorna 401.
> No painel admin, cole o token no campo superior direito; ele salva em `localStorage` e destaca vermelho se estiver vazio.

## Modos de Jogo — Status de Validação (2026-03-18)

Todos os 6 modos testados e confirmados funcionais com `POST /reset` + token:

| Modo | Status |
|------|--------|
| `survival` | ✅ OK |
| `gincana` | ✅ OK |
| `warfare` | ✅ OK |
| `economy` | ✅ OK |
| `gangwar` | ✅ OK |
| `hybrid` | ✅ OK |

## Interfaces Web

| Interface | URL | Descrição |
|-----------|-----|----------|
| Ilha ao vivo | `http://localhost:8001/frontend/index.html` | Observer 3D com WebSocket, replay e benchmark ao vivo |
| Dashboard | `http://localhost:8001/frontend/dashboard.html` | Métricas, gráficos, scoreboard global e exportações |
| Modelos | `http://localhost:8001/frontend/models.html` | Perfis de IA, teste de modelos e registro de agentes |
| **Admin** | `http://localhost:8001/frontend/admin.html` | **Painel gerencial completo** — 8 abas cobrindo F01-F20 |

> Não abra os arquivos `.html` por `file://`. Sirva tudo via `/frontend/` para manter WebSocket e fetches no mesmo host.

### Painel Admin — 8 Abas

| Aba | Features |
|-----|----------|
| 🌍 Mundo | Reset de modo, patch ao vivo, spawn, eventos admin, sessões |
| 🤖 Agentes | Lista ao vivo, registro, F01 Comandante, F03 Inspector, F07 Aliança/Reputação |
| 🎮 Modos | Seletor visual de game_mode com cards interativos |
| ⚔️ Warfare | F12-F16: gincana, warfare, arremesso, papéis táticos, território |
| 💰 Economia | F10/F17-F20: craft, trade, mercado, contratos, GangWar, black market |
| 🔔 Webhooks | F11: registro, teste, histórico de entregas, stats |
| 📊 Benchmark | F02/F06/F09: comparador A/B, temporadas, ELO, versões de perfil |
| 🧠 Avançado | Torneios, eventos dinâmicos F04, missões F08, memórias, rate limit |

**Autenticação:** Cole o `ADMIN_TOKEN` no campo do canto superior direito do painel. O token é salvo automaticamente em `localStorage`.

## Perfis de IA

| Perfil | Provider | Modelo | Custo |
|--------|----------|--------|-------|
| `claude-kiro` ⭐ | Kiro | `kr/claude-sonnet-4.5` | grátis |
| `claude-haiku` | Kiro | `kr/claude-haiku-4.5` | grátis |
| `kimi-thinking` | iFlow | `if/kimi-k2` | grátis |
| `qwen-coder` | iFlow | `if/qwen3-coder-plus` | grátis |
| `kimi-groq` | Groq | `groq/moonshotai/kimi-k2-instruct` | grátis |
| `gemini-flash` | Gemini CLI | `gc/gemini-2.5-flash` | grátis |
| `llama-groq` | Groq | `groq/llama-3.3-70b-versatile` | grátis |

## Estrutura do Projeto

```text
ilhadaia/
├── README.md
├── .env.example
├── docs/
│   ├── ARCHITECTURE.md          arquitetura detalhada
│   ├── API_REFERENCE.md         endpoints e exemplos
│   ├── FEATURE_PLAN.md          roadmap completo
│   └── DEVELOPMENT_GUIDE.md     setup e extensão
└── backend/
    ├── main.py                  FastAPI app + todos os endpoints REST
    ├── agent.py                 classe Agent com vitals, memória, benchmark
    ├── world.py                 World + tick loop + integração de engines
    ├── runtime/
    │   ├── thinker.py           orquestrador de decisão de IA
    │   ├── profiles.py          catálogo de perfis builtin
    │   ├── gincana_engine.py    F12 — Gincana
    │   ├── warfare_engine.py    F13-F16 — Warfare
    │   ├── economy_engine.py    F10/F17-F19 — Economy
    │   └── gangwar_engine.py    F20 — Guerra de Gangues
    ├── storage/
    │   ├── session_store.py     sessões e scores (SQLite)
    │   ├── webhook_manager.py   F11 — webhooks com retry e histórico
    │   ├── decision_log.py      log NDJSON de decisões
    │   ├── replay_store.py      snapshots por tick
    │   └── memory_store.py      AgentMemory persistente
    └── tests/
        └── test_engine.py       174 testes automatizados
```

## Resetar Estado Local

```bash
find backend/data -type f -delete
find backend/logs -type f -delete
find backend -maxdepth 1 \( -name 'hall_of_fame.json' -o -name 'world_settings.json' \) -delete
```

## Validação

```bash
pytest backend/tests/test_engine.py -q
# resultado: 174 passed, 1 skipped
```

## Licença

Projeto de estudo e experimentação de agentes de IA.
