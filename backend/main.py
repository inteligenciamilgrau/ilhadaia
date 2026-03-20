import asyncio
import csv
import io
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx
from pydantic import BaseModel, Field
from typing import Optional

# T18: Rate Limiting
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMIT_ENABLED = True
except ImportError:
    limiter = None
    _rate_limit_exceeded_handler = None
    RateLimitExceeded = None
    RATE_LIMIT_ENABLED = False

# ── Configuração ──────────────────────────────────────────────────────────────
load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev_token_123")
AUTHORIZED_IDS = [id.strip() for id in os.getenv("AUTHORIZED_IDS", "777").split(",") if id.strip()]
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

from world import World
from agent import Agent
from storage.decision_log import DecisionLog
from storage.session_store import SessionStore
from storage.replay_store import ReplayStore
from storage.memory_store import MemoryStore           # T22
from storage.webhook_manager import WebhookManager     # T24
from runtime.thinker import Thinker
from runtime.profiles import (
    AgentProfile,
    list_profiles,
    get_profile,
    BUILTIN_PROFILES,
    OMNIROUTER_URL,
    OMNIROUTER_API_KEY,
)
from runtime.tournament_runner import TournamentRunner  # T20

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("BBB_IA")

# ── Módulos de storage e runtime ──────────────────────────────────────────────
decision_log = DecisionLog(log_dir="logs")
session_store = SessionStore(db_path="data/ilhadaia.db")
replay_store = ReplayStore(replay_dir="data/replays", snapshot_interval=5)
memory_store = MemoryStore(db_path="data/ilhadaia.db")  # T22
webhook_manager = WebhookManager(db_path="data/ilhadaia.db")  # T24
thinker: Optional[Thinker] = None

# ── Estado global ─────────────────────────────────────────────────────────────
world = World()
world.reset_agents(Agent)

_current_session_id: Optional[str] = None

# Torneios em memória + runner
TOURNAMENTS: dict[str, dict] = {}
tournament_runner: Optional[TournamentRunner] = None
_notified_finished_tournaments: set[str] = set()

# ── Models ────────────────────────────────────────────────────────────────────
class JoinRequest(BaseModel):
    agent_id: str = Field(..., json_schema_extra={"example": "777"})
    name: str = Field(..., json_schema_extra={"example": "Visitante"})
    personality: str = Field(..., json_schema_extra={"example": "Curioso e amigável"})

class ActionRequest(BaseModel):
    thought: str = ""
    action: str = "wait"
    speak: str = ""
    target_name: str = ""
    params: dict = {}

class AgentRegistration(BaseModel):
    owner_id: str
    owner_name: str = ""
    agent_name: str
    persona: str = "Estratégico e adaptável"
    profile_id: str = "claude-kiro"

class TournamentConfig(BaseModel):
    name: str
    max_agents: int = 8
    duration_ticks: int = 500
    allowed_profiles: list[str] = []
    reset_on_finish: bool = True


class ResetRequest(BaseModel):
    player_count: int = 4
    game_mode: str = "survival"


class AISettingsRequest(BaseModel):
    ai_provider: str
    ai_model: str
    omniroute_url: str


def _normalize_provider(provider: Optional[str]) -> str:
    # Mantem compatibilidade com valores antigos, mas o runtime agora opera
    # apenas via endpoints OpenAI-compatible.
    return "omnirouter"


def _normalize_omni_base_url(url: Optional[str]) -> str:
    value = (url or OMNIROUTER_URL).strip().rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    return value or OMNIROUTER_URL


def _catalog_api_key() -> str:
    return OMNIROUTER_API_KEY


def _default_model_for_provider(provider: str) -> str:
    return get_profile("claude-kiro").model

# ── Auth ───────────────────────────────────────────────────────────────────────
async def verify_admin_token(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        logger.warning(f"Unauthorized access attempt with token: {x_admin_token}")
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid or missing Admin Token")
    return x_admin_token

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _current_session_id, thinker, tournament_runner
    # === STARTUP ===
    thinker = Thinker(decision_log=decision_log)

    async def _thinker_decider(agent, context, tick):
        if thinker is None or _current_session_id is None:
            return await agent.act(context)
        return await thinker.think(
            agent=agent,
            world_context=context,
            current_tick=tick,
            session_id=_current_session_id,
        )

    world.set_ai_decider(_thinker_decider)
    _world_settings = {
        "ai_interval": world.ai_interval,
        "player_count": world.player_count,
        "ai_provider": world.ai_provider,
        "ai_model": world.ai_model,
        "omniroute_url": world.omniroute_url,
    }
    _current_session_id = session_store.create_session(_world_settings, game_mode=world.game_mode)
    world.set_session_id(_current_session_id)
    decision_log.start_session(_current_session_id)
    replay_store.start_session(_current_session_id)
    task = asyncio.create_task(world_loop())
    # T20: iniciar tournament runner
    tournament_runner = TournamentRunner(TOURNAMENTS, world, session_store)
    tournament_runner.start()
    logger.info(f"🌍 World simulation started — session: {_current_session_id}")

    yield

    # === SHUTDOWN ===
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    replay_store.close()
    decision_log.close()
    tournament_runner.stop() if tournament_runner else None
    memory_store.close()
    webhook_manager.close()
    session_store.close()
    logger.info("🛑 World simulation stopped cleanly.")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="BBB de IA - Backend Engine", lifespan=lifespan)

# T18: inicialização de rate limiting (quando slowapi estiver instalado)
if RATE_LIMIT_ENABLED and limiter and _rate_limit_exceeded_handler and RateLimitExceeded:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

def _rate_limit(limit: str):
    """Decorator condicional de rate limit."""
    def decorator(func):
        if RATE_LIMIT_ENABLED and limiter:
            return limiter.limit(limit)(func)
        return func
    return decorator

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS + ["null"],  # "null" = file:// origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Frontend estático ─────────────────────────────────────────────────────────
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/frontend", StaticFiles(directory=_frontend_dir), name="frontend")

# ── WebSocket ─────────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> bool:
        await websocket.accept()
        try:
            await websocket.send_text(json.dumps({"type": "init", "data": world.get_state()}))
        except WebSocketDisconnect:
            logger.info("Client disconnected before init payload was sent.")
            return False
        except Exception as exc:
            logger.info("Client connection dropped during init payload: %s", exc)
            return False

        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")
        return True

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        msg_str = json.dumps(message)
        stale_connections: list[WebSocket] = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(msg_str)
            except WebSocketDisconnect:
                stale_connections.append(connection)
            except Exception as exc:
                stale_connections.append(connection)
                logger.info("Dropping stale WebSocket connection during broadcast: %s", exc)

        for connection in stale_connections:
            self.disconnect(connection)

manager = ConnectionManager()

async def _dispatch_webhooks_from_events(events: list[dict]) -> None:
    """F11: Dispara webhooks para eventos críticos (expandido com 16 tipos)."""
    tasks = []
    for event in events:
        action = event.get("action", "")
        base = {
            "agent_id": event.get("agent_id", ""),
            "agent_name": event.get("name", ""),
            "tick": world.ticks,
            "event_msg": event.get("event_msg", ""),
            "game_mode": world.game_mode,
        }
        # Eventos originais
        if action in ("die", "death"):
            tasks.append(webhook_manager.fire_event("agent_dead", base))
        elif action == "zombie":
            tasks.append(webhook_manager.fire_event("zombie", base))
        # F04 — Eventos dinâmicos / F12 — Gincana / F13-F16 — Warfare / F20 — GangWar
        elif action == "checkpoint_captured":
            tasks.append(webhook_manager.fire_event("checkpoint_captured", base))
        elif action == "artifact_delivered":
            tasks.append(webhook_manager.fire_event("artifact_delivered", base))
        elif action == "gincana_end":
            tasks.append(webhook_manager.fire_event("gincana_end", {
                **base, "gincana": world.gincana.get_state()
            }))
        elif action == "warfare_end":
            tasks.append(webhook_manager.fire_event("warfare_end", {
                **base, "warfare": world.warfare.get_state()
            }))
        elif action == "gangwar_end":
            tasks.append(webhook_manager.fire_event("gangwar_end", {
                **base, "gangwar": world.gangwar.get_state()
            }))
        elif action == "sabotage":
            tasks.append(webhook_manager.fire_event("sabotage", base))
        # F17 — Trade / F18 — Mercado / F19 — Contratos
        elif action == "trade":
            tasks.append(webhook_manager.fire_event("trade", base))
        elif action == "market_buy":
            tasks.append(webhook_manager.fire_event("market_buy", base))
        elif action == "market_sell":
            tasks.append(webhook_manager.fire_event("market_sell", base))
        elif action == "contract_fulfilled":
            tasks.append(webhook_manager.fire_event("contract_fulfilled", base))
        # Genérico: winner_declared
        elif action in ("win", "winner_declared"):
            tasks.append(webhook_manager.fire_event("winner_declared", {
                **base, "winner": event.get("agent_id")
            }))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

# ── Game Loop ─────────────────────────────────────────────────────────────────
async def world_loop():
    while True:
        try:
            events = await world.tick()

            if events == "AUTO_RESET":
                world.reset_agents(Agent)
                events = []
                await manager.broadcast({"type": "reset", "data": world.get_state()})
            else:
                # Atualizar scores no SQLite a cada 10 ticks
                if world.ticks % 10 == 0 and _current_session_id:
                    for agent in world.agents:
                        try:
                            session_store.upsert_agent_score(_current_session_id, agent)
                            if getattr(agent, "owner_id", ""):
                                memory_store.save(agent)
                        except Exception as e:
                            logger.error(f"Error persisting score for agent {agent.name}: {e}")
                    # Snapshot de replay
                    replay_store.maybe_snapshot(world.ticks, world.get_state())

            if isinstance(events, list) and events:
                asyncio.create_task(_dispatch_webhooks_from_events(events))

            # Notifica fim de torneio uma única vez por torneio
            for tournament_id, tournament in TOURNAMENTS.items():
                if tournament.get("status") == "finished" and tournament_id not in _notified_finished_tournaments:
                    _notified_finished_tournaments.add(tournament_id)
                    asyncio.create_task(webhook_manager.fire_event("tournament_end", {
                        "tournament_id": tournament_id,
                        "winner": tournament.get("winner", {}),
                        "tick": world.ticks,
                    }))

            if events or world.ticks % 1 == 0:
                await manager.broadcast({
                    "type": "update",
                    "data": world.get_state(),
                    "events": events if isinstance(events, list) else []
                })
        except Exception as e:
            logger.error(f"Error in world loop: {e}")
        await asyncio.sleep(1)

# ── Endpoints básicos ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    connected = await manager.connect(websocket)
    if not connected:
        return
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received message from client: {data}")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)

@app.get("/")
def read_root():
    return {
        "status": "World engine is running",
        "ticks": world.ticks,
        "started": world.started,
        "session_id": _current_session_id,
        "agents": len(world.agents),
        "game_mode": world.game_mode,
    }

@app.post("/reset", dependencies=[Depends(verify_admin_token)])
async def reset_game(req: ResetRequest = ResetRequest()):
    global _current_session_id
    # Valida game_mode
    valid_modes = set(World.MODE_SIZES.keys())
    game_mode = req.game_mode if req.game_mode in valid_modes else "survival"
    if _current_session_id:
        for agent in world.agents:
            if getattr(agent, "owner_id", ""):
                memory_store.save(agent)
        replay_store.force_snapshot(world.ticks, world.get_state())
        session_store.end_session(_current_session_id, None, None)
    # Atualizar game_mode no mundo
    world.game_mode = game_mode
    _world_settings = {
        "ai_interval": world.ai_interval,
        "player_count": world.player_count,
        "ai_provider": world.ai_provider,
        "ai_model": world.ai_model,
        "omniroute_url": world.omniroute_url,
        "game_mode": game_mode,
    }
    _current_session_id = session_store.create_session(_world_settings, game_mode=game_mode)
    world.set_session_id(_current_session_id)
    decision_log.start_session(_current_session_id)
    replay_store.start_session(_current_session_id)
    world.reset_agents(Agent, player_count=req.player_count)
    world.started = True  # Auto-start the newly reset world
    await manager.broadcast({"type": "reset", "data": world.get_state()})
    return {"status": "World reset successful", "player_count": req.player_count, "game_mode": game_mode, "session_id": _current_session_id}

@app.post("/settings/ai_interval")
async def set_ai_interval(interval: int):
    world.ai_interval = max(0, interval)
    world._save_history()
    return {"status": "Interval updated", "new_interval": world.ai_interval}


@app.get("/settings/ai")
async def get_ai_settings():
    return {
        "scope": "catalog_default",
        "note": "Perfis por agente continuam sendo a fonte de verdade. Esta configuracao salva apenas o preset/catalogo auxiliar da UI.",
        "ai_provider": world.ai_provider,
        "ai_model": world.ai_model,
        "omniroute_url": world.omniroute_url,
    }


@app.post("/settings/ai")
async def set_ai_settings(req: AISettingsRequest):
    provider = _normalize_provider(req.ai_provider)
    world.ai_provider = provider
    world.ai_model = (req.ai_model or "").strip() or _default_model_for_provider(provider)
    world.omniroute_url = _normalize_omni_base_url(req.omniroute_url)
    world._save_history()
    logger.info(
        "AI catalog settings updated: provider=%s model=%s url=%s",
        world.ai_provider,
        world.ai_model,
        world.omniroute_url,
    )
    return {
        "status": "AI catalog settings updated",
        "scope": "catalog_default",
        "ai_provider": world.ai_provider,
        "ai_model": world.ai_model,
        "omniroute_url": world.omniroute_url,
    }


@app.get("/models")
async def get_models(
    provider: Optional[str] = None, 
    url: Optional[str] = None,
    is_registration: bool = False,
    api_key: Optional[str] = None
):
    """Lista modelos de um endpoint OpenAI-compatible. 
    is_registration=True retorna apenas modelos dinâmicos do endpoint (lista limpa).
    """
    target_provider = _normalize_provider(provider or world.ai_provider)
    target_url = _normalize_omni_base_url(url or world.omniroute_url)

    final_models: list[dict] = []
    seen_ids: set[str] = set()

    def add_model(model_id: str, name: str, source: str = "curated") -> None:
        if model_id and model_id not in seen_ids:
            final_models.append({"id": model_id, "name": name, "source": source})
            seen_ids.add(model_id)

    if not is_registration:
        builtin_profiles = [
            p for p in BUILTIN_PROFILES.values()
            if _normalize_provider(p.provider) == target_provider
        ]
        for profile in builtin_profiles:
            add_model(profile.model, f"{profile.profile_id} ({profile.model})", "builtin_profile")

    try:
        # Usar a chave provida ou a padrão do catálogo
        auth_key = api_key or _catalog_api_key()
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{target_url}/models",
                headers={"Authorization": f"Bearer {auth_key}"},
            )
            if response.status_code == 200:
                payload = response.json()
                for model in payload.get("data", []) if isinstance(payload, dict) else []:
                    model_id = model.get("id")
                    if model_id:
                        add_model(model_id, model.get("name", model_id), "dynamic")
            else:
                logger.warning(
                    "Failed to fetch OpenAI-compatible models from %s: %s",
                    target_url,
                    response.status_code,
                )
    except Exception as exc:
        logger.error("Error proxying OpenAI-compatible models from %s: %s", target_url, exc)

    if not is_registration:
        curated_omni = [
            ("kr/claude-sonnet-4.5", "Claude Sonnet 4.5 via Kiro"),
            ("kr/claude-haiku-4.5", "Claude Haiku 4.5 via Kiro"),
            ("if/kimi-k2", "Kimi K2 via iFlow"),
            ("if/qwen3-coder-plus", "Qwen3 Coder Plus via iFlow"),
            ("gc/gemini-2.5-flash", "Gemini 2.5 Flash via gateway"),
            ("groq/moonshotai/kimi-k2-instruct", "Kimi K2 Instruct via Groq"),
            ("groq/llama-3.3-70b-versatile", "Llama 3.3 70B via Groq"),
            ("gpt-4o-mini", "GPT-4o Mini"),
            ("gpt-4o", "GPT-4o"),
        ]
        for model_id, name in curated_omni:
            add_model(model_id, name)

    if not final_models:
        add_model(_default_model_for_provider(target_provider), "Padrao do provider", "default")

    return {
        "scope": "catalog",
        "provider": target_provider,
        "base_url": target_url,
        "models": final_models,
    }

# ── Sessions, Scoreboard & Replay ─────────────────────────────────────────────

@app.get("/sessions")
async def list_sessions(limit: int = 20):
    return {"sessions": session_store.get_sessions(limit=limit)}

@app.get("/sessions/{session_id}/replay")
async def get_replay(session_id: str):
    frames = replay_store.load_replay(session_id)
    if not frames:
        raise HTTPException(404, "Sessão não encontrada ou sem dados de replay")
    return {"session_id": session_id, "total_frames": len(frames), "frames": frames}

@app.get("/sessions/{session_id}/replay/frame/{tick}")
async def get_replay_frame(session_id: str, tick: int):
    frames = replay_store.load_replay(session_id)
    frame = next((f for f in frames if f["tick"] == tick), None)
    if not frame:
        raise HTTPException(404, f"Frame tick={tick} não encontrado")
    return frame

@app.get("/world/scoreboard")
async def get_scoreboard(limit: int = 50):
    return {"scoreboard": session_store.get_scoreboard(limit=limit)}

# ── Profiles ──────────────────────────────────────────────────────────────────

@app.get("/profiles")
async def get_profiles():
    return {"profiles": list_profiles()}

@app.post("/debug/test_model")
async def debug_test_model(req: dict):
    """Teste rápido de um perfil de IA ou configuração avulsa."""
    profile_id = req.get("profile_id")
    # T14+: suporte a config avulsa (URL, Key, Model)
    manual_config = req.get("manual_config")
    message = req.get("message", "Oi! Responda apenas com 'Conectado!' se você me ouve.")
    
    if manual_config:
        # Normalizar a URL provida ou usar a padrão
        raw_url = manual_config.get("base_url") or OMNIROUTER_URL
        target_url = _normalize_omni_base_url(raw_url)
        target_key = manual_config.get("api_key") or OMNIROUTER_API_KEY
        
        # Criar perfil temporário em memória
        profile = AgentProfile(
            profile_id="ad-hoc-test",
            provider="omnirouter",
            model=manual_config.get("model", ""),
            base_url=target_url,
            api_key=target_key,
            max_tokens=100,
            temperature=0.0
        )
        # Para testes ad-hoc, não usamos o cache do thinker para evitar reuso de config antiga
        from runtime.adapters.openai_compatible import OpenAICompatibleAdapter
        adapter = OpenAICompatibleAdapter(
            base_url=profile.base_url,
            model=profile.model,
            api_key=profile.api_key,
        )
    elif profile_id:
        profile = get_profile(profile_id)
        if not profile:
            raise HTTPException(404, "Profile not found")
        if thinker is None:
            raise HTTPException(503, "Thinker not initialized")
        adapter = thinker.get_adapter(profile)
    else:
        raise HTTPException(400, "profile_id or manual_config is required")
    
    t0 = time.time()
    try:
        # Usamos uma versão simplificada do think para o teste
        response = await adapter.think(
            system_prompt="Você é um assistente de teste. Responda de forma curta.",
            user_context=message,
            max_tokens=50,
            temperature=0.0
        )
        latency = (time.time() - t0) * 1000
        
        # O adapter captura exceções internas e as coloca no campo 'thought' como "Error: ..."
        is_error = response.thought.startswith("Error:") or response.speech == "(silêncio)"
        
        return {
            "ok": not is_error,
            "profile_id": profile_id,
            "model": profile.model,
            "response": response.speech,
            "thought": response.thought,
            "latency_ms": response.latency_ms or latency,
            "tokens": response.prompt_tokens + response.completion_tokens,
            "error": response.thought if is_error else None
        }
    except Exception as e:
        return {
            "ok": False,
            "profile_id": profile_id,
            "error": str(e)
        }

@app.post("/profiles/add", dependencies=[Depends(verify_admin_token)])
async def add_profile(req: dict):
    """Adiciona um novo perfil ao arquivo profiles.py permanentemente."""
    pid = req.get("profile_id")
    model = req.get("model")
    base_url = req.get("base_url")
    api_key = req.get("api_key")
    
    if not all([pid, model]):
        raise HTTPException(400, "profile_id and model are required")
        
    # Validar se já existe
    if pid in BUILTIN_PROFILES:
        raise HTTPException(400, f"Profile '{pid}' already exists")

    # Caminho do arquivo
    profiles_path = os.path.join(os.path.dirname(__file__), "runtime", "profiles.py")
    
    # Gerar o código do novo perfil
    new_entry = f'\n    "{pid}": AgentProfile(\n'
    new_entry += f'        profile_id="{pid}",\n'
    new_entry += f'        provider="omnirouter",\n'
    new_entry += f'        model="{model}",\n'
    if base_url:
        new_entry += f'        base_url="{base_url}",\n'
    else:
        new_entry += f'        base_url=OMNIROUTER_URL,\n'
    if api_key:
        new_entry += f'        api_key="{api_key}",\n'
    else:
        new_entry += f'        api_key=OMNIROUTER_API_KEY,\n'
    new_entry += f'        max_tokens=300,\n'
    new_entry += f'        token_budget=10_000,\n'
    new_entry += f'        cooldown_ticks=3,\n'
    new_entry += f'        temperature=0.7,\n'
    new_entry += f'    ),'

    try:
        with open(profiles_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Encontrar o local para inserir (dentro do dicionário BUILTIN_PROFILES)
        # Procuramos o fechamento do dicionário antes das funções auxiliares
        marker = "}  # end of BUILTIN_PROFILES"
        if marker not in content:
            # Fallback se o comentário não existir
            content = content.replace("}\n\n\ndef get_profile", "}" + marker + "\n\n\ndef get_profile")
            
        if marker in content:
            new_content = content.replace(marker, new_entry + "\n" + marker)
            with open(profiles_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        else:
            # Fallback robusto: procurar o último '}' antes de 'def get_profile'
            parts = content.split("def get_profile")
            if len(parts) > 1:
                dict_part = parts[0].rstrip()
                last_brace_idx = dict_part.rfind("}")
                if last_brace_idx != -1:
                    new_content = dict_part[:last_brace_idx] + new_entry + "\n}" + parts[1]
                    # Adicionar o marcador para as próximas vezes
                    new_content = new_content.replace("\n}", "\n}" + marker)
                    with open(profiles_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
            else:
                raise Exception("Could not find insertion point in profiles.py")

        return {"status": "success", "message": f"Profile '{pid}' added! Restart backend to apply."}
    except Exception as e:
        logger.error(f"Failed to add profile: {e}")
        raise HTTPException(500, f"Failed to modify profiles.py: {e}")

# ── Agent Registration (T14) ──────────────────────────────────────────────────

@app.post("/agents/register", dependencies=[Depends(verify_admin_token)])
@_rate_limit("10/minute")
async def register_agent(request: Request, reg: AgentRegistration):
    """Owner registra um agente customizado na ilha."""
    if reg.profile_id not in BUILTIN_PROFILES:
        raise HTTPException(400, f"Profile '{reg.profile_id}' não existe. Disponíveis: {list(BUILTIN_PROFILES.keys())}")

    max_agents = getattr(world, 'player_count', 12) + 4  # permite agentes externos além dos NPCs
    if len(world.agents) >= max_agents:
        raise HTTPException(409, "Limite de agentes atingido")

    profile = get_profile(reg.profile_id)
    agent_id = f"agent_{reg.owner_id}_{int(time.time())}"

    new_agent = Agent(
        name=reg.agent_name[:30],
        personality=reg.persona[:200],
        start_x=random.randint(2, 17),
        start_y=random.randint(2, 17),
        agent_id=agent_id,
    )
    new_agent.profile_id = reg.profile_id
    new_agent.owner_id = reg.owner_id
    new_agent.token_budget = profile.token_budget
    new_agent.cooldown_ticks = profile.cooldown_ticks

    memory_store.load(new_agent)
    memory_store.save(new_agent) # Garantir que o perfil e nome sejam lembrados imediatamente
    world.add_agent(new_agent)
    logger.info(f"🤖 Registered agent: {reg.agent_name} [{reg.profile_id}] by {reg.owner_id}")
    asyncio.create_task(webhook_manager.fire_event("agent_registered", {
        "agent_id": agent_id,
        "agent_name": reg.agent_name,
        "owner_id": reg.owner_id,
        "profile_id": reg.profile_id,
        "tick": world.ticks,
    }))

    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "join", "event_msg": f"{reg.agent_name} ENTROU NA ILHA! (Modelo: {profile.model})", "agent_id": agent_id}]
    })

    return {
        "agent_id": agent_id,
        "message": f"{reg.agent_name} entrou na ilha!",
        "profile": reg.profile_id,
        "model": profile.model,
        "token_budget": profile.token_budget,
    }

@app.get("/agents/all")
async def get_all_agents():
    """
    Retorna a lista completa de agentes organizada por:
    1. NPCs Ativos (João, Maria, etc. que estão no mundo)
    2. NPCs Potenciais/Inativos (System default + Extra names que não estão no mundo)
    3. Agentes de Usuário (Registrados via API)
    """
    # 1. Definir NPCs do Sistema (Fixos + Extras)
    system_npcs = ["João", "Maria", "Zeca", "Elly"]
    extra_npcs = [name for name, _ in world.extra_names]
    all_npc_names = set(system_npcs + extra_npcs)
    
    active_npcs_list = []
    potential_npcs_list = []
    user_agents_list = []
    
    seen_npc_names = set()
    seen_user_keys = set() # (owner_id, name)
    
    # --- 1. Processar Agentes Ativos no Mundo ---
    for a in world.agents:
        is_npc = a.name in all_npc_names and not getattr(a, "owner_id", "")
        
        agent_data = {
            "id": a.id,
            "name": a.name,
            "owner_id": getattr(a, "owner_id", ""),
            "profile_id": getattr(a, "profile_id", ""),
            "hp": a.hp,
            "is_alive": a.is_alive,
            "is_zombie": getattr(a, "is_zombie", False),
            "tokens_used": getattr(a, "tokens_used", 0),
            "token_budget": getattr(a, "token_budget", 10000),
            "benchmark": getattr(a, "benchmark", {}),
            "status": "active" if a.is_alive else "dead"
        }
        
        if is_npc:
            active_npcs_list.append(agent_data)
            seen_npc_names.add(a.name)
        else:
            user_agents_list.append(agent_data)
            seen_user_keys.add((getattr(a, "owner_id", ""), a.name))

    # --- 2. Processar NPCs Potenciais (que ainda não entraram ou estão inativos) ---
    for name in all_npc_names:
        if name not in seen_npc_names:
            # Tentar ver se tem memória desse NPC para pegar o profile_id real
            sys_id = None
            if name == "João": sys_id = "sys_joao"
            elif name == "Maria": sys_id = "sys_maria"
            elif name == "Zeca": sys_id = "sys_zeca"
            elif name == "Elly": sys_id = "sys_elly"
            
            profile_id = "claude-kiro" # fallback
            if sys_id and sys_id in world.system_agent_overrides:
                profile_id = world.system_agent_overrides[sys_id]
            
            potential_npcs_list.append({
                "id": sys_id or f"potential_{name.lower()}",
                "name": name,
                "owner_id": "",
                "profile_id": profile_id,
                "hp": 0,
                "is_alive": False,
                "is_zombie": False,
                "tokens_used": 0,
                "token_budget": 0,
                "benchmark": {},
                "status": "potential"
            })

    # --- 3. Processar Agentes de Usuário da Memória (Inativos) ---
    all_registered = memory_store.list_agents_with_memory()
    for reg in all_registered:
        owner_id = reg["owner_id"]
        name = reg["agent_name"]
        key = (owner_id, name)
        
        if owner_id != "" and key not in seen_user_keys:
            user_agents_list.append({
                "id": f"historic_{owner_id}||{name}",
                "name": name,
                "owner_id": owner_id,
                "profile_id": reg.get("profile_id", "unknown"),
                "hp": 0,
                "is_alive": False,
                "is_zombie": False,
                "tokens_used": 0,
                "token_budget": 0,
                "benchmark": {},
                "status": "inactive",
                "last_seen": reg["updated_at"]
            })
            seen_user_keys.add(key)

    # Combinar tudo na ordem solicitada: Ativos NPC -> Potenciais NPC -> Agentes Usuário
    final_list = active_npcs_list + potential_npcs_list + user_agents_list
    
    return {"agents": final_list}


@app.get("/agents/{agent_id}/state")
async def get_agent_state(agent_id: str):
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return {
        "id": agent.id,
        "name": agent.name,
        "health": agent.hp,
        "position": {"x": agent.x, "y": agent.y},
        "tokens_used": getattr(agent, "tokens_used", 0),
        "token_budget": getattr(agent, "token_budget", 10000),
        "profile_id": getattr(agent, "profile_id", "claude-kiro"),
        "benchmark": getattr(agent, "benchmark", {}),
        "recent_memory": agent.memory[-5:] if hasattr(agent, "memory") else [],
    }

# ── Tournaments (T15) ─────────────────────────────────────────────────────────

@app.post("/tournaments", dependencies=[Depends(verify_admin_token)])
@_rate_limit("5/minute")
async def create_tournament(request: Request, config: TournamentConfig):
    t_id = f"tournament_{int(time.time())}"
    config_data = config.model_dump()
    TOURNAMENTS[t_id] = {
        "id": t_id,
        "name": config.name,
        "status": "waiting",
        "config": config_data,
        "max_agents": config.max_agents,
        "duration_ticks": config.duration_ticks,
        "reset_on_finish": config.reset_on_finish,
        "allowed_profiles": config.allowed_profiles or list(BUILTIN_PROFILES.keys()),
        "start_tick": None,
        "started_at": None,
        "end_tick": None,
        "registered_agents": [],
    }
    return {"tournament_id": t_id, "config": config_data}

@app.post("/tournaments/{t_id}/join")
async def join_tournament(request: Request, t_id: str, reg: AgentRegistration):
    t = TOURNAMENTS.get(t_id)
    if not t:
        raise HTTPException(404, "Torneio não existe")
    if t["status"] != "waiting":
        raise HTTPException(409, "Torneio já começou")
    if len(t["registered_agents"]) >= t["max_agents"]:
        raise HTTPException(409, "Torneio lotado")
    if t["allowed_profiles"] and reg.profile_id not in t["allowed_profiles"]:
        raise HTTPException(400, f"Perfil não permitido. Permitidos: {t['allowed_profiles']}")

    result = await register_agent(request, reg)
    t["registered_agents"].append(result["agent_id"])
    return result

@app.post("/tournaments/{t_id}/start", dependencies=[Depends(verify_admin_token)])
async def start_tournament(t_id: str):
    t = TOURNAMENTS.get(t_id)
    if not t:
        raise HTTPException(404, "Torneio não existe")
    t["status"] = "active"
    t["start_tick"] = world.ticks
    t["started_at"] = time.time()
    t["end_tick"] = world.ticks + t["duration_ticks"]
    world.active_tournament_id = t_id
    world.tournament_end_tick = t["end_tick"]
    _notified_finished_tournaments.discard(t_id)
    return {"message": "Torneio iniciado!", "end_tick": t["end_tick"]}

@app.get("/tournaments")
async def list_tournaments():
    return {"tournaments": list(TOURNAMENTS.values())}

# ── Remote Agent API (mantido) ────────────────────────────────────────────────

@app.post("/join")
async def join_island(req: JoinRequest):
    if req.agent_id not in AUTHORIZED_IDS:
        raise HTTPException(status_code=401, detail="ID de Acesso não autorizado.")

    existing_agent = next((a for a in world.agents if a.id == req.agent_id), None)
    if existing_agent:
        if existing_agent.is_alive:
            raise HTTPException(status_code=400, detail="Este ID já está em uso por um agente Vivo.")
        else:
            world.remove_agent(req.agent_id)

    new_agent = Agent(req.name, req.personality, 10, 10, is_remote=True, agent_id=req.agent_id)
    world.add_agent(new_agent)

    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "join", "event_msg": f"{new_agent.name} CHEGOU NA ILHA!", "agent_id": new_agent.id, "name": new_agent.name}]
    })

    return {"status": "Joined successfully", "agent_id": new_agent.id, "name": new_agent.name,
            "personality": new_agent.personality, "coords": [new_agent.x, new_agent.y]}

@app.get("/agent/{agent_id}/context")
async def get_agent_context(agent_id: str):
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    context = world._get_context_for_agent(agent)
    context["status"] = {
        "hp": agent.hp,
        "hunger": agent.hunger,
        "thirst": agent.thirst,
        "is_alive": agent.is_alive,
        "is_zombie": getattr(agent, "is_zombie", False),
        "inventory": agent.inventory,
        "pos": [agent.x, agent.y],
        "tokens_used": getattr(agent, "tokens_used", 0),
        "token_budget": getattr(agent, "token_budget", 10000),
    }
    return context

@app.post("/agent/{agent_id}/action")
async def agent_action(agent_id: str, req: ActionRequest):
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.is_alive:
        return {"status": "Agent is dead", "action": "ignored"}

    action_data = {"agent_id": agent.id, "name": agent.name, "thought": req.thought,
                   "action": req.action, "speak": req.speak, "target_name": req.target_name}
    for k, v in req.params.items():
        action_data[k] = v

    world._apply_action(agent, action_data)
    world.ai_events.append(action_data)
    return {"status": "Action processed", "action": req.action}

@app.delete("/agent/{agent_id}", dependencies=[Depends(verify_admin_token)])
async def delete_agent(agent_id: str):
    """Remove um agente da ilha (se ativo) ou da memória persistente (se histórico)."""
    # Caso 1: Agente Histórico (prefixo 'historic_owner_name')
    if agent_id.startswith("historic_"):
        # historic_owner||name
        core = agent_id.replace("historic_", "", 1)
        if "||" in core:
            parts = core.split("||", 1)
            owner_id = parts[0]
            agent_name = parts[1]
            deleted = memory_store.delete(owner_id, agent_name)
            if deleted:
                return {"status": "Memory deleted", "agent_id": agent_id, "owner_id": owner_id, "name": agent_name}
        raise HTTPException(status_code=404, detail=f"Memória persistente não encontrada para {agent_id}")

    # Caso 2: Agente Ativo na Ilha
    success = world.remove_agent(agent_id)
    if success:
        state = world.get_state()
        await manager.broadcast({
            "type": "update", "data": state,
            "events": [{"action": "busy", "event_msg": "UM AGENTE FOI REMOVIDO PELO ADMINISTRADOR.", "agent_id": agent_id}]
        })
        return {"status": "Agent removed", "agent_id": agent_id, "state": state}
    
    raise HTTPException(status_code=404, detail="Agente ativo não encontrado")

class AgentProfileUpdate(BaseModel):
    profile_id: str

@app.patch("/agent/{agent_id}/profile", dependencies=[Depends(verify_admin_token)])
async def update_agent_profile(agent_id: str, up: AgentProfileUpdate):
    """Atualiza o perfil de IA de um agente (ativo ou histórico)."""
    if up.profile_id not in BUILTIN_PROFILES:
        raise HTTPException(400, f"Perfil '{up.profile_id}' não existe.")

    # Caso 1: Agente Ativo
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if agent:
        agent.profile_id = up.profile_id
        # Se for um agente do sistema, salvar o override de forma permanente
        if agent_id.startswith("sys_"):
            world.system_agent_overrides[agent_id] = up.profile_id
            world._save_history()
        
        # Sincronizar com a memória persistente também, se o agente tiver dono
        if getattr(agent, "owner_id", ""):
            memory_store.save(agent)
            
        return {"status": "Agent profile updated", "agent_id": agent_id, "profile_id": up.profile_id}

    # Caso 2: Agente Histórico
    if agent_id.startswith("historic_"):
        core = agent_id.replace("historic_", "", 1)
        if "||" in core:
            parts = core.split("||", 1)
            owner_id = parts[0]
            agent_name = parts[1]
            
            try:
                memory_store.conn.execute(
                    "UPDATE agent_memories SET profile_id=? WHERE owner_id=? AND agent_name=?",
                    (up.profile_id, owner_id, agent_name)
                )
                memory_store.conn.commit()
                return {"status": "Historical agent profile updated", "agent_id": agent_id, "profile_id": up.profile_id}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao atualizar memória: {e}")

    # Caso 3: NPCs Potenciais (não ativos no momento)
    if agent_id.startswith("sys_") or agent_id.startswith("potential_"):
        # Salvar o override no mundo
        world.system_agent_overrides[agent_id] = up.profile_id
        world._save_history()
        return {"status": "Potential NPC profile updated", "agent_id": agent_id, "profile_id": up.profile_id}

    raise HTTPException(status_code=404, detail="Agente não encontrado")


# ═══════════════════════════════════════════════════════════════════════
# F01 — Modo Comandante por Linguagem Natural
# ═══════════════════════════════════════════════════════════════════════

class CommandRequest(BaseModel):
    command: str
    expire_ticks: int = 30  # Número de ticks antes de expirar


@app.post("/agents/{agent_id}/command")
async def set_agent_command(agent_id: str, req: CommandRequest):
    """F01: Define um comando humano para o agente."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if not agent.is_alive:
        raise HTTPException(400, "Agent is dead")
    agent.human_command = req.command.strip()
    agent.command_expire_tick = world.ticks + req.expire_ticks
    agent.command_source = "human"
    logger.info(f"F01: Command set for {agent.name}: '{agent.human_command}' (expires tick {agent.command_expire_tick})")
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🎮 Operador enviou comando para {agent.name}: '{agent.human_command}'", "agent_id": agent_id}]
    })
    return {"status": "Command set", "agent_id": agent_id, "command": agent.human_command, "expires_at_tick": agent.command_expire_tick}


@app.post("/agents/{agent_id}/command/cancel")
async def cancel_agent_command(agent_id: str):
    """F01: Cancela o comando humano ativo e libera o agente para autonomia."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    agent.human_command = None
    agent.command_expire_tick = 0
    agent.command_source = "ai"
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🔓 {agent.name} liberado para autonomia.", "agent_id": agent_id}]
    })
    return {"status": "Command cancelled", "agent_id": agent_id}


@app.get("/agents/{agent_id}/command")
async def get_agent_command(agent_id: str):
    """F01: Retorna o estado atual do comando humano do agente."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    is_active = (
        agent.human_command is not None and
        world.ticks < agent.command_expire_tick
    )
    return {
        "agent_id": agent_id,
        "human_command": agent.human_command if is_active else None,
        "command_source": agent.command_source,
        "expires_at_tick": agent.command_expire_tick,
        "is_active": is_active,
        "ticks_remaining": max(0, agent.command_expire_tick - world.ticks) if is_active else 0,
    }


# ═══════════════════════════════════════════════════════════════════════
# F03 — Decision Inspector
# ═══════════════════════════════════════════════════════════════════════

@app.get("/agents/{agent_id}/decisions")
async def get_agent_decisions(agent_id: str, n: int = 5):
    """F03: Retorna as últimas N decisões de um agente."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if _current_session_id is None:
        return {"agent_id": agent_id, "decisions": []}
    decisions = decision_log.get_recent(_current_session_id, agent_id, n=min(n, 20))
    return {"agent_id": agent_id, "agent_name": agent.name, "decisions": decisions}


@app.get("/agents/{agent_id}/memory/relevant")
async def get_agent_memory(agent_id: str):
    """F03: Retorna a memória relevante do agente (short_term + episodic resumidos)."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    mem_dict = agent.agent_memory.to_dict() if hasattr(agent, "agent_memory") else {}
    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "short_term": mem_dict.get("short_term", [])[-10:],
        "episodic": mem_dict.get("episodic", [])[-5:],
        "relational": mem_dict.get("relational", {}),
        "tokens_used": getattr(agent, "tokens_used", 0),
        "token_budget": getattr(agent, "token_budget", 10000),
    }


# ═══════════════════════════════════════════════════════════════════════
# F05 — Console de Intervenção Admin ao Vivo
# ═══════════════════════════════════════════════════════════════════════

class AdminSpawnRequest(BaseModel):
    type: str                     # tipo do objeto (stone, tree, supply_crate, etc)
    x: int
    y: int
    extra: dict = {}              # campos extras opcionais


class AdminEventRequest(BaseModel):
    event_type: str               # tempestade, seca, radio, suprimentos, eclipse
    message: str = ""


class AdminProfileRequest(BaseModel):
    agent_id: str
    profile_id: str


class AdminProfilePathRequest(BaseModel):
    profile_id: str


class AdminWorldPatchRequest(BaseModel):
    started: Optional[bool] = None
    ai_interval: Optional[int] = None
    game_over: Optional[bool] = None
    event_chance: Optional[float] = None


@app.post("/admin/spawn", dependencies=[Depends(verify_admin_token)])
async def admin_spawn(req: AdminSpawnRequest):
    """F05: Spawna um objeto no mapa. Requer X-Admin-Token."""
    if not (0 <= req.x < world.size and 0 <= req.y < world.size):
        raise HTTPException(400, f"Coordenadas fora do mapa {world.size}x{world.size}")
    entity_id = f"admin_spawn_{req.type}_{world.ticks}_{req.x}_{req.y}"
    obj = {"type": req.type, "x": req.x, "y": req.y, **req.extra}
    world.add_entity(entity_id, obj)
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🔧 Admin criou {req.type} em ({req.x},{req.y})"}]
    })
    return {"status": "spawned", "entity_id": entity_id, "object": obj}


@app.post("/admin/event", dependencies=[Depends(verify_admin_token)])
async def admin_trigger_event(req: AdminEventRequest):
    """F05: Dispara um evento global na ilha. Requer X-Admin-Token."""
    event_messages = {
        "tempestade": "⛈️ UMA TEMPESTADE VIOLENTA VARREU A ILHA! Todos perdem 5HP!",
        "seca": "🌵 A SECA CHEGOU! Recursos de água estão escassos por 30 ticks.",
        "suprimentos": "📦 UM CRATE DE SUPRIMENTOS CAIU DO CÉU!",
        "radio": "📻 Um rádio misterioso emite sinais da ilha...",
        "eclipse": "🌑 ECLIPSE TOTAL! A ilha mergulhou na escuridão.",
    }
    msg = req.message or event_messages.get(req.event_type, f"🚨 Evento: {req.event_type}")

    # Efeitos do evento tempestade
    if req.event_type == "tempestade":
        for agent in world.agents:
            if agent.is_alive and not getattr(agent, "is_zombie", False):
                agent.hp = max(0, agent.hp - 5)

    # Efeito suprimentos: spawnar supply crate no centro
    if req.event_type == "suprimentos":
        cx, cy = world.size // 2 + random.randint(-3, 3), world.size // 2 + random.randint(-3, 3)
        world.add_entity(f"event_crate_{world.ticks}", {
            "type": "supply_crate", "x": cx, "y": cy,
            "name": "Crate Admin", "loot": ["fruit", "water_bottle"]
        })

    world.ai_events.append({"action": "busy", "event_msg": msg})
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": msg}]
    })
    return {"status": "event_triggered", "event_type": req.event_type, "message": msg}


@app.post("/admin/world/patch", dependencies=[Depends(verify_admin_token)])
async def admin_world_patch(req: AdminWorldPatchRequest):
    """F05: Aplica patch controlado em parâmetros do mundo ao vivo."""
    applied = {}
    if req.started is not None:
        world.started = req.started
        applied["started"] = world.started
    if req.ai_interval is not None:
        if req.ai_interval < 0:
            raise HTTPException(400, "ai_interval deve ser >= 0")
        world.ai_interval = req.ai_interval
        applied["ai_interval"] = world.ai_interval
    if req.game_over is not None:
        world.game_over = req.game_over
        applied["game_over"] = world.game_over
    if req.event_chance is not None:
        if not (0.0 <= req.event_chance <= 1.0):
            raise HTTPException(400, "event_chance deve estar entre 0 e 1")
        world.event_chance = req.event_chance
        applied["event_chance"] = world.event_chance

    if not applied:
        raise HTTPException(400, "Nenhum campo de patch enviado")

    await manager.broadcast({
        "type": "update",
        "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🛠️ Admin aplicou patch no mundo: {applied}"}],
    })
    return {"status": "patched", "applied": applied, "world_state": world.get_state()}


@app.post("/admin/agent/profile", dependencies=[Depends(verify_admin_token)])
async def admin_change_profile(req: AdminProfileRequest):
    """F05: Altera o perfil de IA de um agente ao vivo. Requer X-Admin-Token."""
    from runtime.profiles import BUILTIN_PROFILES, get_profile
    agent = next((a for a in world.agents if a.id == req.agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if req.profile_id not in BUILTIN_PROFILES:
        raise HTTPException(400, f"Perfil '{req.profile_id}' não encontrado. Disponíveis: {list(BUILTIN_PROFILES.keys())}")
    old_profile = agent.profile_id
    agent.profile_id = req.profile_id
    profile = get_profile(req.profile_id)
    agent.token_budget = profile.token_budget
    agent.cooldown_ticks = profile.cooldown_ticks
    logger.info(f"F05: Profile of {agent.name} changed {old_profile} → {req.profile_id}")
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🔄 Admin: {agent.name} trocou de perfil para '{req.profile_id}'"}]
    })
    return {"status": "profile_changed", "agent_id": req.agent_id, "old_profile": old_profile, "new_profile": req.profile_id}


@app.post("/admin/agent/{agent_id}/profile", dependencies=[Depends(verify_admin_token)])
async def admin_change_profile_by_path(agent_id: str, req: AdminProfilePathRequest):
    """F05: Alias RESTful para alteração de perfil de agente por path param."""
    return await admin_change_profile(AdminProfileRequest(agent_id=agent_id, profile_id=req.profile_id))


@app.get("/admin/world/state")
async def admin_world_state(x_admin_token: str = Header(None)):
    """F05: Retorna estado detalhado do mundo para admin (inclui todos os campos)."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")
    state = world.get_state()
    state["game_mode"] = world.game_mode
    state["world_size"] = world.size
    state["pending_spawns"] = len(world.pending_spawns)
    state["thinking_agents"] = list(world.thinking_agents)
    return state



# ═══════════════════════════════════════════════════════════════════════
# T18 — Rate Limiting (slowapi)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/rate-limit/status")
async def rate_limit_status(request: Request):
    """Informa se o rate limit está ativo e as regras configuradas."""
    return {
        "rate_limit_enabled": RATE_LIMIT_ENABLED,
        "limits": {
            "POST /agents/register": "10/minute per IP",
            "POST /tournaments": "5/minute per IP (admin)",
            "POST /webhooks/register": "20/hour per IP",
        } if RATE_LIMIT_ENABLED else "Rate limiting not active (slowapi not installed)"
    }

# ═══════════════════════════════════════════════════════════════════════
# T19 — Exportação CSV/JSON
# ═══════════════════════════════════════════════════════════════════════

@app.get("/sessions/{session_id}/export")
async def export_session(session_id: str, format: str = "json"):
    """
    Exporta os frames de replay de uma sessão como JSON ou CSV.
    Query param: ?format=json (default) | csv
    """
    frames = replay_store.load_replay(session_id)
    if not frames:
        raise HTTPException(404, f"Sessão '{session_id}' não encontrada ou sem frames.")

    if format == "csv":
        output = io.StringIO()
        if frames:
            # Flatten frames para CSV
            fieldnames = ["tick", "session_id", "agent_count"]
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for frame in frames:
                writer.writerow({
                    "tick": frame.get("tick", ""),
                    "session_id": session_id,
                    "agent_count": len(frame.get("state", {}).get("agents", [])),
                })
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=session_{session_id}.csv"}
        )

    # JSON default
    return {"session_id": session_id, "frame_count": len(frames), "frames": frames}

@app.get("/world/scoreboard/export")
async def export_scoreboard(format: str = "json"):
    """
    Exporta o scoreboard global como JSON ou CSV.
    Query param: ?format=json | csv
    """
    board = session_store.get_scoreboard(limit=200)
    if format == "csv":
        output = io.StringIO()
        if board:
            writer = csv.DictWriter(output, fieldnames=list(board[0].keys()))
            writer.writeheader()
            writer.writerows(board)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=scoreboard.csv"}
        )
    return {"scoreboard": board, "total": len(board)}

@app.get("/sessions/{session_id}/decisions/export")
async def export_decisions(session_id: str, format: str = "json"):
    """Exporta o decision log NDJSON de uma sessão como JSON ou CSV."""
    import os
    log_files = [f for f in os.listdir("logs") if session_id in f and f.endswith(".ndjson")]
    if not log_files:
        raise HTTPException(404, f"Decision log para sessão '{session_id}' não encontrado.")

    records = []
    with open(os.path.join("logs", log_files[0])) as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    if format == "csv" and records:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(records[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=decisions_{session_id}.csv"}
        )
    return {"session_id": session_id, "decisions": records, "total": len(records)}

# ═══════════════════════════════════════════════════════════════════════
# T20 — Tournament Status & Leaderboard aprimorado
# ═══════════════════════════════════════════════════════════════════════

@app.get("/tournaments/{tournament_id}/status")
async def tournament_status(tournament_id: str):
    """Retorna status detalhado de um torneio com progresso e estimativa de encerramento."""
    if tournament_runner is None:
        raise HTTPException(503, "TournamentRunner não iniciado")
    status = tournament_runner.get_status(tournament_id)
    if not status:
        raise HTTPException(404, f"Torneio '{tournament_id}' não encontrado")
    return status

@app.get("/tournaments/{tournament_id}/leaderboard")
async def tournament_leaderboard(tournament_id: str):
    """Retorna leaderboard ao vivo ou final do torneio."""
    if tournament_id not in TOURNAMENTS:
        raise HTTPException(404, f"Torneio '{tournament_id}' não encontrado")
    leaderboard = tournament_runner.get_leaderboard(tournament_id) if tournament_runner else []
    return {
        "tournament_id": tournament_id,
        "status": TOURNAMENTS[tournament_id].get("status", "unknown"),
        "leaderboard": leaderboard,
    }

# ═══════════════════════════════════════════════════════════════════════
# T22 — Memória Persistente entre sessões
# ═══════════════════════════════════════════════════════════════════════

@app.get("/memories")
async def list_memories(owner_id: Optional[str] = None):
    """Lista agentes com memória persistente salva."""
    agents_with_memory = memory_store.list_agents_with_memory()
    if owner_id:
        agents_with_memory = [m for m in agents_with_memory if m["owner_id"] == owner_id]
    return {"memories": agents_with_memory, "total": len(agents_with_memory)}

@app.post("/memories/save/{agent_id}")
async def save_agent_memory(agent_id: str):
    """Salva manualmente a memória de um agente no SQLite."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agente não encontrado")
    if not getattr(agent, "owner_id", ""):
        raise HTTPException(400, "Agente não tem owner_id — memória persistente requer owner")
    memory_store.save(agent)
    return {"status": "memory_saved", "agent_id": agent_id, "agent_name": agent.name}

@app.delete("/memories/{owner_id}/{agent_name}", dependencies=[Depends(verify_admin_token)])
async def delete_agent_memory(owner_id: str, agent_name: str):
    """Remove a memória persistente de um agente (admin)."""
    deleted = memory_store.delete(owner_id, agent_name)
    if not deleted:
        raise HTTPException(404, "Memória não encontrada")
    return {"status": "deleted", "owner_id": owner_id, "agent_name": agent_name}

# ═══════════════════════════════════════════════════════════════════════
# T24 — Webhooks de Notificação
# ═══════════════════════════════════════════════════════════════════════

class WebhookRegistration(BaseModel):
    owner_id: str
    url: str
    events: list[str] = ["all"]
    secret: str = ""


class WebhookTestRequest(BaseModel):
    owner_id: str


@app.post("/webhooks")
@app.post("/webhooks/register")
@_rate_limit("20/hour")
async def register_webhook(request: Request, reg: WebhookRegistration):
    """
    Registra uma URL de webhook para receber notificações de eventos.
    Eventos válidos: death, win, zombie, tournament_end, agent_registered, all
    """
    result = webhook_manager.register(
        owner_id=reg.owner_id,
        url=reg.url,
        events=reg.events,
        secret=reg.secret,
    )
    return result


@app.post("/webhooks/test", dependencies=[Depends(verify_admin_token)])
async def test_webhook_alias(req: WebhookTestRequest):
    """F11: Alias de teste de webhook com owner_id no body."""
    return await test_webhook(req.owner_id)


@app.get("/webhooks/deliveries", dependencies=[Depends(verify_admin_token)])
async def webhooks_deliveries(webhook_id: Optional[str] = None, limit: int = 50):
    """F11: Retorna histórico de entregas de webhooks."""
    history = webhook_manager.get_delivery_history(webhook_id=webhook_id, limit=limit)
    return {"count": len(history), "deliveries": history}


@app.get("/webhooks/{owner_id}")
async def list_webhooks(owner_id: str):
    """Lista todos os webhooks registrados para um owner."""
    hooks = webhook_manager.list_for_owner(owner_id)
    return {"owner_id": owner_id, "webhooks": hooks}

@app.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, owner_id: str):
    """Remove um webhook pelo ID (requer owner_id para validação)."""
    deleted = webhook_manager.delete(webhook_id, owner_id)
    if not deleted:
        raise HTTPException(404, "Webhook não encontrado ou owner incorreto")
    return {"status": "deleted", "webhook_id": webhook_id}

@app.post("/webhooks/test/{owner_id}", dependencies=[Depends(verify_admin_token)])
async def test_webhook(owner_id: str):
    """Dispara um evento de teste para os webhooks do owner (admin)."""
    fired = await webhook_manager.fire_event("test", {
        "message": "BBBia webhook test",
        "owner_id": owner_id,
        "tick": world.ticks,
    })
    return {"status": "fired", "webhooks_notified": fired}

# ═══════════════════════════════════════════════════════════════════════
# Info geral do sistema (summary de todos os módulos ativos)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/system/info")
async def system_info():
    """Retorna informações de todos os módulos ativos no backend."""
    return {
        "version": "turbinada-v0.5",
        "ticks": world.ticks,
        "started": world.started,
        "session_id": _current_session_id,
        "modules": {
            "thinker": thinker is not None,
            "tournament_runner": tournament_runner is not None and tournament_runner._running,
            "memory_store": True,
            "webhook_manager": True,
            "replay_store": True,
            "decision_log": True,
        },
        "rate_limit": RATE_LIMIT_ENABLED,
        "active_tournaments": len([t for t in TOURNAMENTS.values() if t.get("status") in ("active", "running")]),
        "registered_webhooks": webhook_manager.conn.execute("SELECT COUNT(*) FROM webhooks").fetchone()[0],
        "agents_with_memory": len(memory_store.list_agents_with_memory()),
    }


# ═══════════════════════════════════════════════════════════════════════
# F06 — Temporadas e Ranking ELO
# ═══════════════════════════════════════════════════════════════════════

class SeasonRequest(BaseModel):
    name: str
    game_mode: str = "survival"
    description: str = ""


@app.post("/seasons", dependencies=[Depends(verify_admin_token)])
async def create_season(req: SeasonRequest):
    """F06: Cria uma nova temporada. Requer X-Admin-Token."""
    sid = session_store.create_season(req.name, req.game_mode, req.description)
    return {"status": "created", "season_id": sid, "name": req.name, "game_mode": req.game_mode}


@app.get("/seasons")
async def list_seasons():
    """F06: Lista todas as temporadas."""
    return {"seasons": session_store.get_seasons()}


@app.post("/seasons/{season_id}/end", dependencies=[Depends(verify_admin_token)])
async def end_season(season_id: str):
    """F06: Encerra uma temporada. Requer X-Admin-Token."""
    session_store.end_season(season_id)
    return {"status": "ended", "season_id": season_id}


@app.get("/seasons/{season_id}/leaderboard")
async def season_leaderboard(season_id: str):
    """F06: Retorna o leaderboard ELO da temporada."""
    return {"season_id": season_id, "leaderboard": session_store.get_leaderboard_elo(season_id)}


@app.post("/seasons/{season_id}/record", dependencies=[Depends(verify_admin_token)])
async def record_elo_session(season_id: str, session_id: str = None):
    """F06: Calcula e persiste o ELO dos agentes com base na sessão atual.
    Usa o placar dos agentes vivos ordenado por score_total DESC.
    """
    target_session = session_id or _current_session_id
    if not target_session:
        raise HTTPException(400, "Nenhuma sessão ativa")

    # Monta placements a partir dos agentes atuais
    placements = sorted(
        [{"profile_id": getattr(a, "profile_id", "claude-kiro"),
          "score_total": a.benchmark.get("score", 0.0),
          "agent_name": a.name}
         for a in world.agents],
        key=lambda x: -x["score_total"]
    )
    if not placements:
        raise HTTPException(400, "Nenhum agente encontrado")

    results = session_store.record_elo_session(season_id, target_session, placements)
    return {"status": "recorded", "season_id": season_id, "session_id": target_session, "results": results}


@app.get("/elo/{profile_id}")
async def get_profile_elo(profile_id: str, season_id: str = None):
    """F06: Retorna o ELO de um perfil (na temporada especificada ou em todas)."""
    if season_id:
        elo = session_store.get_elo(season_id, profile_id)
        return {"profile_id": profile_id, "season_id": season_id, "elo": elo}
    # Todas as temporadas
    seasons = session_store.get_seasons()
    result = {
        "profile_id": profile_id,
        "elo_by_season": {
            s["id"]: {"name": s["name"], "elo": session_store.get_elo(s["id"], profile_id)}
            for s in seasons
        }
    }
    return result


# ═══════════════════════════════════════════════════════════════════════
# F02 — Comparador A/B de Perfis
# ═══════════════════════════════════════════════════════════════════════

class ABRequest(BaseModel):
    profile_a: str
    profile_b: str
    game_mode: str = "survival"
    ticks: int = 200        # duração em ticks


@app.post("/benchmarks/ab", dependencies=[Depends(verify_admin_token)])
@app.post("/ab/compare", dependencies=[Depends(verify_admin_token)])
async def ab_compare(req: ABRequest):
    """F02: Registra manualmente um resultado A/B a partir do estado atual da sessão.
    Compara os dois primeiros agentes que usam os profiles indicados.
    """
    from runtime.profiles import BUILTIN_PROFILES
    from uuid import uuid4

    if req.profile_a not in BUILTIN_PROFILES:
        raise HTTPException(400, f"Perfil A '{req.profile_a}' não encontrado")
    if req.profile_b not in BUILTIN_PROFILES:
        raise HTTPException(400, f"Perfil B '{req.profile_b}' não encontrado")

    agents_a = [a for a in world.agents if getattr(a, "profile_id", "") == req.profile_a]
    agents_b = [a for a in world.agents if getattr(a, "profile_id", "") == req.profile_b]

    if not agents_a:
        raise HTTPException(400, f"Nenhum agente ativo com perfil '{req.profile_a}'")
    if not agents_b:
        raise HTTPException(400, f"Nenhum agente ativo com perfil '{req.profile_b}'")

    ag_a = agents_a[0]
    ag_b = agents_b[0]

    run_id = str(uuid4())
    result = session_store.record_ab_result(
        run_id=run_id,
        session_id=_current_session_id or "manual",
        profile_a=req.profile_a,
        profile_b=req.profile_b,
        score_a=ag_a.benchmark.get("score", 0.0),
        score_b=ag_b.benchmark.get("score", 0.0),
        ticks_a=ag_a.benchmark.get("ticks_survived", 0),
        ticks_b=ag_b.benchmark.get("ticks_survived", 0),
        tokens_a=getattr(ag_a, "tokens_used", 0),
        tokens_b=getattr(ag_b, "tokens_used", 0),
        game_mode=req.game_mode,
    )
    return {"status": "recorded", **result}


def _get_ab_run_or_404(run_id: str) -> dict:
    cur = session_store.conn.execute(
        "SELECT * FROM ab_results WHERE run_id=? ORDER BY recorded_at DESC LIMIT 1",
        (run_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Run A/B '{run_id}' não encontrado")
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


@app.get("/benchmarks/ab/{run_id}")
async def get_ab_run(run_id: str):
    """F02: Retorna os detalhes de uma execução A/B específica."""
    return {"run": _get_ab_run_or_404(run_id)}


@app.get("/benchmarks/ab/{run_id}/report")
async def get_ab_run_report(run_id: str):
    """F02: Retorna relatório consolidado da execução A/B."""
    run = _get_ab_run_or_404(run_id)
    score_delta = float(run.get("score_a", 0.0)) - float(run.get("score_b", 0.0))
    tokens_a = max(float(run.get("tokens_a", 0.0)), 1.0)
    tokens_b = max(float(run.get("tokens_b", 0.0)), 1.0)
    report = {
        "run_id": run_id,
        "winner": run.get("winner"),
        "profiles": {"A": run.get("profile_a"), "B": run.get("profile_b")},
        "scores": {"A": run.get("score_a", 0.0), "B": run.get("score_b", 0.0), "delta": score_delta},
        "ticks": {"A": run.get("ticks_a", 0), "B": run.get("ticks_b", 0)},
        "tokens": {"A": run.get("tokens_a", 0), "B": run.get("tokens_b", 0)},
        "efficiency": {
            "A_score_per_1k_tokens": round(float(run.get("score_a", 0.0)) / tokens_a * 1000, 4),
            "B_score_per_1k_tokens": round(float(run.get("score_b", 0.0)) / tokens_b * 1000, 4),
        },
        "game_mode": run.get("game_mode"),
        "recorded_at": run.get("recorded_at"),
    }
    return {"report": report, "raw": run}


@app.get("/ab/results")
async def get_ab_results(profile_a: str = None, profile_b: str = None, limit: int = 20):
    """F02: Lista resultados de comparações A/B. Filtra por perfil se fornecido."""
    results = session_store.get_ab_summary(profile_a=profile_a, profile_b=profile_b, limit=limit)
    return {"count": len(results), "results": results}


@app.get("/ab/stats")
async def get_ab_stats():
    """F02: Retorna estatísticas agregadas de vitórias/derrotas/empates por par de perfis."""
    return {"stats": session_store.get_ab_stats()}


# ═══════════════════════════════════════════════════════════════════════
# F09 — Versionamento de Perfis e Prompts
# ═══════════════════════════════════════════════════════════════════════

class ProfileVersionRequest(BaseModel):
    note: str = ""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    token_budget: Optional[int] = None
    cooldown_ticks: Optional[int] = None
    system_prompt_override: Optional[str] = None
    created_by: str = "user"


@app.post("/profiles/{profile_id}/versions", dependencies=[Depends(verify_admin_token)])
async def save_profile_version(profile_id: str, req: ProfileVersionRequest):
    """F09: Salva snapshot da versão atual de um perfil + overrides opcionais. Requer X-Admin-Token."""
    from runtime.profiles import BUILTIN_PROFILES, get_profile
    if profile_id not in BUILTIN_PROFILES:
        raise HTTPException(400, f"Perfil '{profile_id}' não encontrado")

    profile = get_profile(profile_id)
    snapshot = {
        "model": profile.model,
        "provider": profile.provider,
        "temperature": req.temperature if req.temperature is not None else profile.temperature,
        "max_tokens": req.max_tokens if req.max_tokens is not None else profile.max_tokens,
        "token_budget": req.token_budget if req.token_budget is not None else profile.token_budget,
        "cooldown_ticks": req.cooldown_ticks if req.cooldown_ticks is not None else profile.cooldown_ticks,
        "system_prompt_override": req.system_prompt_override or None,
    }
    version = session_store.save_profile_version(profile_id, snapshot, req.note, req.created_by)
    return {"status": "saved", "profile_id": profile_id, "version": version, "snapshot": snapshot}


@app.get("/profiles/{profile_id}/versions")
async def list_profile_versions(profile_id: str):
    """F09: Lista o histórico de versões de um perfil."""
    versions = session_store.get_profile_versions(profile_id)
    return {"profile_id": profile_id, "total": len(versions), "versions": versions}


@app.get("/profiles/versions/all")
async def list_all_profile_versions():
    """F09: Lista o histórico global de todas as versões de perfis."""
    return {"versions": session_store.get_profile_versions_all()}


@app.post("/profiles/{profile_id}/activate/{version}", dependencies=[Depends(verify_admin_token)])
@app.post("/profiles/{profile_id}/versions/{version}/rollback", dependencies=[Depends(verify_admin_token)])
async def rollback_profile_version(profile_id: str, version: int):
    """F09: Aplica snapshot de uma versão específica ao perfil ao vivo. Requer X-Admin-Token."""
    snapshot = session_store.rollback_profile_version(profile_id, version)
    if not snapshot:
        raise HTTPException(404, f"Versão {version} do perfil '{profile_id}' não encontrada")

    # Aplica snapshot aos agentes que usam este perfil
    applied_to = []
    for agent in world.agents:
        if getattr(agent, "profile_id", "") == profile_id:
            if "token_budget" in snapshot:
                agent.token_budget = snapshot["token_budget"]
            if "cooldown_ticks" in snapshot:
                agent.cooldown_ticks = snapshot["cooldown_ticks"]
            applied_to.append(agent.name)

    logger.info(f"F09: Rollback {profile_id} → v{version} aplicado a {applied_to}")
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🔄 Perfil '{profile_id}' revertido para v{version}"}]
    })
    return {"status": "rolled_back", "profile_id": profile_id, "version": version,
            "snapshot": snapshot, "applied_to_agents": applied_to}


# ═══════════════════════════════════════════════════════════════════════
# F04 — Eventos Dinâmicos da Ilha
# ═══════════════════════════════════════════════════════════════════════

@app.get("/events/active")
async def get_active_event():
    """F04: Retorna o evento global ativo no momento."""
    return {"active_event": world.active_event, "ticks": world.ticks}


@app.get("/events/history")
async def get_event_history():
    """F04: Retorna o histórico de todos os eventos da sessão."""
    return {"count": len(world.event_history), "events": world.event_history}


@app.post("/events/trigger", dependencies=[Depends(verify_admin_token)])
async def trigger_event_manual(event_type: str):
    """F04: Dispara um evento global manualmente. Requer X-Admin-Token."""
    if event_type not in world.DYNAMIC_EVENTS:
        raise HTTPException(400, f"Tipo inválido. Válidos: {list(world.DYNAMIC_EVENTS.keys())}")
    event = world.trigger_event(event_type)
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "event", "event_msg": f"{event['name']}: {event['message']}"}]
    })
    return {"status": "triggered", "event": event}


@app.get("/events/templates")
@app.get("/events/types")
async def list_event_types():
    """F04: Lista todos os tipos de eventos com efeitos."""
    return {"event_types": {k: {"name": v["name"], "duration": v["duration"],
        "hp_delta": v.get("hp_delta", 0)} for k, v in world.DYNAMIC_EVENTS.items()}}


# ═══════════════════════════════════════════════════════════════════════
# F07 — Reputação Social e Alianças
# ═══════════════════════════════════════════════════════════════════════

class AllianceRequest(BaseModel):
    agent_b_name: str


@app.post("/agents/{agent_id}/alliances")
@app.post("/agents/{agent_id}/alliance")
async def form_alliance(agent_id: str, req: AllianceRequest):
    """F07: Forma aliança entre agente e outro (por nome)."""
    result = world.form_alliance(agent_id, req.agent_b_name)
    if "error" in result:
        raise HTTPException(404, result["error"])
    await manager.broadcast({"type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🤝 Aliança: {result.get('alliance')}"}]})
    return result


@app.delete("/agents/{agent_id}/alliance")
async def break_alliance_endpoint(agent_id: str, betrayal: bool = False):
    """F07: Quebra aliança. betrayal=true aplica penalidade de reputação."""
    result = world.break_alliance(agent_id, betrayal=betrayal)
    if "error" in result:
        raise HTTPException(404, result["error"])
    await manager.broadcast({"type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": "💔 Aliança quebrada"}]})
    return result


@app.post("/agents/{agent_id}/betray")
async def betray_alliance_endpoint(agent_id: str):
    """F07: Rota de traição explícita (equivalente a quebrar aliança com penalidade)."""
    return await break_alliance_endpoint(agent_id, betrayal=True)


@app.get("/agents/{agent_id}/reputation")
async def get_agent_reputation(agent_id: str):
    """F07: Retorna dados de reputação social do agente."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agente não encontrado")
    return {"agent_id": agent.id, "name": agent.name, "alliance": agent.alliance,
            "reputation_score": round(agent.reputation_score, 2),
            "betrayals": agent.betrayals, "promises": agent.promises}


# ═══════════════════════════════════════════════════════════════════════
# F08 — Missões Individuais
# ═══════════════════════════════════════════════════════════════════════

@app.get("/missions/templates")
@app.get("/missions/catalog")
async def get_mission_catalog():
    """F08: Retorna o catálogo completo de missões."""
    return {"count": len(world.mission_catalog), "missions": world.mission_catalog}


@app.post("/missions/assign", dependencies=[Depends(verify_admin_token)])
async def assign_missions_endpoint():
    """F08: Atribui missões aleatórias a todos os agentes. Requer X-Admin-Token."""
    world.assign_missions()
    return {"status": "assigned",
            "assignments": [{"agent": a.name, "mission_id": a.mission_id} for a in world.agents]}


@app.get("/agents/{agent_id}/mission")
async def get_agent_mission(agent_id: str):
    """F08: Retorna o progresso de missão de um agente."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agente não encontrado")
    mission = next((m for m in world.mission_catalog if m["id"] == agent.mission_id), None)
    return {"agent_id": agent.id, "name": agent.name, "mission_id": agent.mission_id,
            "mission": mission, "progress": agent.mission_state.get("progress", 0),
            "target": mission["target"] if mission else None,
            "completed": agent.mission_completed_tick is not None,
            "completed_tick": agent.mission_completed_tick,
            "bonus_score": agent.mission_bonus_score}


@app.get("/missions/progress")
async def get_all_missions_progress():
    """F08: Retorna o progresso de missões de todos os agentes."""
    return {"ticks": world.ticks, "missions": [
        {"agent": a.name, "mission_id": a.mission_id,
         "progress": a.mission_state.get("progress", 0),
         "completed": a.mission_completed_tick is not None,
         "bonus_score": a.mission_bonus_score}
        for a in world.agents]}

# ═══════════════════════════════════════════════════════════════════════
# F12 — Modo Gincana
# ═══════════════════════════════════════════════════════════════════════

class GincanaStartRequest(BaseModel):
    max_ticks: int = 400


@app.post("/modes/gincana/start", dependencies=[Depends(verify_admin_token)])
@app.post("/gincana/start", dependencies=[Depends(verify_admin_token)])
async def gincana_start(req: GincanaStartRequest = GincanaStartRequest()):
    """F12: Inicia a Gincana no mundo atual. Requer X-Admin-Token e game_mode=gincana."""
    if world.game_mode != "gincana":
        raise HTTPException(400, "Mundo não está no modo gincana. Faça /reset com game_mode=gincana.")
    world.gincana.start(max_ticks=req.max_ticks)
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🏁 Gincana iniciada! Máx: {req.max_ticks} ticks"}]
    })
    return {"status": "started", "max_ticks": req.max_ticks, "gincana": world.gincana.get_state()}


@app.post("/gincana/stop", dependencies=[Depends(verify_admin_token)])
async def gincana_stop():
    """F12: Encerra a Gincana e retorna resultado final. Requer X-Admin-Token."""
    result = world.gincana.stop()
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🏆 Gincana encerrada! Vencedor: {result.get('winner_name')}"}]
    })
    return {"status": "stopped", "result": result}


@app.get("/gincana/state")
async def gincana_state():
    """F12: Retorna o estado atual da Gincana (placar, checkpoints, artefato)."""
    return {
        "game_mode": world.game_mode,
        "ticks": world.ticks,
        "gincana": world.gincana.get_state(),
    }


@app.get("/modes/gincana/templates")
@app.get("/gincana/templates")
async def gincana_templates():
    """F12: Retorna os templates e configurações disponíveis para Gincana."""
    return {
        "templates": [
            {"id": "classic", "name": "Gincana Clássica", "max_ticks": 400,
             "description": "4 checkpoints + artefato central. 400 ticks."},
            {"id": "sprint", "name": "Sprint", "max_ticks": 150,
             "description": "Corrida rápida por checkpoints. 150 ticks."},
            {"id": "marathon", "name": "Maratona", "max_ticks": 800,
             "description": "Longa batalha por artefatos. 800 ticks."},
        ],
        "scoring": {
            "checkpoint": 5,
            "delivery": 20,
        }
    }

# ═══════════════════════════════════════════════════════════════════════
# F13-F16 — Modo Warfare
# ═══════════════════════════════════════════════════════════════════════

class WarfareStartRequest(BaseModel):
    max_ticks: int = 600


class ThrowRequest(BaseModel):
    attacker_id: str
    target_x: int
    target_y: int


class TeamRolesRequest(BaseModel):
    roles: dict[str, str] = {}


class ZoneConfigRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    name: Optional[str] = None


@app.post("/modes/warfare/start", dependencies=[Depends(verify_admin_token)])
@app.post("/warfare/start", dependencies=[Depends(verify_admin_token)])
async def warfare_start(req: WarfareStartRequest = WarfareStartRequest()):
    """F13: Inicia o Warfare. Requer X-Admin-Token e game_mode=warfare."""
    if world.game_mode != "warfare":
        raise HTTPException(400, "Mundo não está no modo warfare. Faça /reset com game_mode=warfare.")
    world.warfare.start(max_ticks=req.max_ticks)
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"⚔️ Warfare iniciado! Máx: {req.max_ticks} ticks"}]
    })
    return {"status": "started", "max_ticks": req.max_ticks, "warfare": world.warfare.get_state()}


@app.post("/warfare/stop", dependencies=[Depends(verify_admin_token)])
async def warfare_stop():
    """F13: Encerra o Warfare. Requer X-Admin-Token."""
    result = world.warfare.stop()
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🏴 Warfare encerrado! Facção {result.get('winner_faction', '?').upper()} vence!"}]
    })
    return {"status": "stopped", "result": result}


@app.get("/modes/warfare/state")
@app.get("/warfare/state")
async def warfare_state():
    """F13-F16: Retorna estado completo do Warfare (facções, território, placar)."""
    return {
        "game_mode": world.game_mode,
        "ticks": world.ticks,
        "warfare": world.warfare.get_state(),
    }


@app.post("/actions/throw")
@app.post("/warfare/throw")
async def warfare_throw(req: ThrowRequest):
    """F14: Arremessa uma pedra de um agente para uma posição alvo."""
    events = []
    result = world.warfare.throw_stone(req.attacker_id, req.target_x, req.target_y, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({
            "type": "update", "data": world.get_state(),
            "events": events
        })
    return result


@app.get("/combat/config")
async def combat_config():
    """F14: Configuração de combate por arremesso."""
    from runtime.warfare_engine import THROW_DAMAGE, THROW_RANGE, THROW_AOE_RADIUS, ROLE_BONUSES
    return {
        "throw": {
            "damage": THROW_DAMAGE,
            "range": THROW_RANGE,
            "aoe_radius": THROW_AOE_RADIUS,
        },
        "roles": ROLE_BONUSES,
        "supported_actions": ["throw_stone"],
    }


@app.get("/warfare/roles")
async def warfare_roles():
    """F15: Retorna os papéis táticos atribuídos a cada agente."""
    return {
        "roles": {
            agent.id: {
                "name": agent.name,
                "role": world.warfare.agent_roles.get(agent.id),
                "faction": world.warfare.agent_factions.get(agent.id),
            }
            for agent in world.agents
        },
        "role_bonuses": world.warfare.ROLE_BONUSES if hasattr(world.warfare, "ROLE_BONUSES") else {},
    }


@app.get("/warfare/territory")
async def warfare_territory():
    """F16: Retorna o estado atual do controle de território."""
    zone = world.entities.get("control_zone_center")
    return {
        "territory_holder": world.warfare.territory_holder,
        "contest_ticks": world.warfare.territory_contest_ticks,
        "faction_scores": world.warfare.faction_scores,
        "zone": zone,
    }


@app.post("/teams/{team_id}/roles")
async def set_team_roles(team_id: str, req: TeamRolesRequest):
    """F15: Configura papéis táticos de um time (alpha/beta)."""
    from runtime.warfare_engine import ROLES

    if team_id not in ("alpha", "beta"):
        raise HTTPException(400, "team_id deve ser 'alpha' ou 'beta'")

    team_agents = [a for a in world.agents if world.warfare.agent_factions.get(a.id) == team_id]
    if not team_agents:
        raise HTTPException(400, f"Nenhum agente da facção '{team_id}'. Inicie o modo warfare primeiro.")

    if req.roles:
        for agent_id, role in req.roles.items():
            if role not in ROLES:
                raise HTTPException(400, f"Role inválido '{role}'. Válidos: {ROLES}")
            if world.warfare.agent_factions.get(agent_id) != team_id:
                raise HTTPException(400, f"Agente {agent_id} não pertence ao time '{team_id}'")
            world.warfare.agent_roles[agent_id] = role
            agent = next((a for a in world.agents if a.id == agent_id), None)
            if agent:
                agent.role = role  # type: ignore[attr-defined]
    else:
        # Sem payload explícito, apenas reequilibra papéis em round-robin.
        for idx, agent in enumerate(team_agents):
            role = ROLES[idx % len(ROLES)]
            world.warfare.agent_roles[agent.id] = role
            agent.role = role  # type: ignore[attr-defined]

    return await get_team_roles(team_id)


@app.get("/teams/{team_id}/roles")
async def get_team_roles(team_id: str):
    """F15: Retorna papéis táticos de todos os agentes de um time."""
    if team_id not in ("alpha", "beta"):
        raise HTTPException(400, "team_id deve ser 'alpha' ou 'beta'")

    roles = {}
    for agent in world.agents:
        if world.warfare.agent_factions.get(agent.id) == team_id:
            roles[agent.id] = {
                "name": agent.name,
                "role": world.warfare.agent_roles.get(agent.id),
            }
    return {"team_id": team_id, "roles": roles}


@app.post("/zones/config")
async def configure_zone(req: ZoneConfigRequest):
    """F16: Atualiza configuração da zona central de controle."""
    zone = world.entities.get("control_zone_center")
    if not zone:
        raise HTTPException(404, "Zona de controle central não encontrada")

    if req.x is not None:
        if not (0 <= req.x < world.size):
            raise HTTPException(400, f"x fora do mapa (0..{world.size - 1})")
        zone["x"] = req.x
    if req.y is not None:
        if not (0 <= req.y < world.size):
            raise HTTPException(400, f"y fora do mapa (0..{world.size - 1})")
        zone["y"] = req.y
    if req.name:
        zone["name"] = req.name

    await manager.broadcast({
        "type": "update",
        "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": "📍 Zona de controle atualizada."}],
    })
    return {"status": "updated", "zone": zone}


@app.get("/zones/state")
async def zones_state():
    """F16: Alias de estado de território para consumo por zona."""
    return await warfare_territory()

# ═══════════════════════════════════════════════════════════════════════
# F10+F17+F18+F19 — Economia, Crafting e Contratos
# ═══════════════════════════════════════════════════════════════════════

class CraftRequest(BaseModel):
    agent_id: str
    recipe: str

class BuildRequest(BaseModel):
    agent_id: str
    structure_type: str
    x: int
    y: int

class TradeRequest(BaseModel):
    seller_id: str
    buyer_id: str
    item: str
    price: float

class MarketOrderRequest(BaseModel):
    agent_id: str
    item: str
    qty: int = 1

class ContractPostRequest(BaseModel):
    requester_id: str
    item: str
    qty: int
    reward: float

class ContractFulfillRequest(BaseModel):
    agent_id: str
    contract_id: int


class ContractFulfillPathRequest(BaseModel):
    agent_id: str


@app.post("/modes/economy/start", dependencies=[Depends(verify_admin_token)])
@app.post("/economy/start", dependencies=[Depends(verify_admin_token)])
async def economy_start():
    """F17: Inicializa a economia — dá moedas iniciais a todos os agentes. Requer X-Admin-Token."""
    world.economy.start()
    initial_coins = next(iter(world.economy.coins.values()), 0)
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"💰 Economia iniciada! Cada agente recebeu {initial_coins} moedas"}]
    })
    return {"status": "started", "economy": world.economy.get_state()}


@app.get("/modes/economy/state")
@app.get("/economy/state")
async def economy_state():
    """F17-F19: Retorna estado completo da economia."""
    return {"ticks": world.ticks, "economy": world.economy.get_state()}


@app.get("/recipes")
@app.get("/economy/recipes")
async def economy_recipes():
    """F10: Lista todas as receitas de crafting disponíveis."""
    from runtime.economy_engine import RECIPES
    return {"recipes": RECIPES}


@app.post("/craft")
@app.post("/economy/craft")
async def economy_craft(req: CraftRequest):
    """F10: Agente crafta um item a partir de ingredientes no inventário."""
    events = []
    result = world.economy.craft(req.agent_id, req.recipe, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.post("/build")
@app.post("/economy/build")
async def economy_build(req: BuildRequest):
    """F10: Agente constrói uma estrutura no mapa."""
    events = []
    result = world.economy.build(req.agent_id, req.structure_type, req.x, req.y, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.post("/economy/trade")
async def economy_trade(req: TradeRequest):
    """F17: Transfere item entre dois agentes por moedas."""
    events = []
    result = world.economy.trade(req.seller_id, req.buyer_id, req.item, req.price, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.get("/economy/coins")
async def economy_coins():
    """F17: Retorna saldo de moedas de todos os agentes."""
    return {
        "coins": {
            agent.name: world.economy.coins.get(agent.id, 0)
            for agent in world.agents
        }
    }


@app.get("/economy/market")
async def economy_market():
    """F18: Retorna preços e estoques atuais do mercado central."""
    return {
        "prices": world.economy.market_prices,
        "stock": world.economy.market_stock,
        "tx_count": len(world.economy.market_tx_log),
    }


@app.get("/market/prices")
async def market_prices():
    """F18: Alias para leitura dos preços do mercado central."""
    state = await economy_market()
    return {"prices": state["prices"], "stock": state["stock"], "tx_count": state["tx_count"]}


@app.post("/market/recalculate")
async def market_recalculate():
    """F18: Força recálculo dos preços de mercado pela oferta/demanda atual."""
    snapshot = world.economy.recalculate_market(reason="api_manual_recalculate")
    await manager.broadcast({
        "type": "update",
        "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": "📈 Mercado recalculado manualmente."}],
    })
    return snapshot


@app.post("/market/buy")
@app.post("/economy/market/buy")
async def economy_market_buy(req: MarketOrderRequest):
    """F18: Agente compra item do mercado central."""
    events = []
    result = world.economy.market_buy(req.agent_id, req.item, req.qty, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.post("/market/sell")
@app.post("/economy/market/sell")
async def economy_market_sell(req: MarketOrderRequest):
    """F18: Agente vende item ao mercado central."""
    events = []
    result = world.economy.market_sell(req.agent_id, req.item, req.qty, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.get("/contracts")
@app.get("/economy/contracts")
async def economy_contracts():
    """F19: Lista todos os contratos (abertos e cumpridos)."""
    return {
        "open": [c for c in world.economy.contracts if c["status"] == "open"],
        "fulfilled": [c for c in world.economy.contracts if c["status"] == "fulfilled"],
        "total": len(world.economy.contracts),
    }


@app.post("/contracts")
@app.post("/economy/contracts")
async def economy_post_contract(req: ContractPostRequest):
    """F19: Publica um contrato de entrega de item."""
    result = world.economy.post_contract(req.requester_id, req.item, req.qty, req.reward)
    if "error" in result:
        raise HTTPException(400, result["error"])
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"📜 Novo contrato #{result['id']}: {req.qty}x {req.item} por {req.reward} moedas"}]
    })
    return result


@app.post("/economy/contracts/fulfill")
async def economy_fulfill_contract(req: ContractFulfillRequest):
    """F19: Agente cumpre um contrato e recebe recompensa."""
    events = []
    result = world.economy.fulfill_contract(req.agent_id, req.contract_id, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.post("/contracts/{contract_id}/fulfill")
async def economy_fulfill_contract_by_path(contract_id: int, req: ContractFulfillPathRequest):
    """F19: Alias RESTful para cumprimento de contrato."""
    events = []
    result = world.economy.fulfill_contract(req.agent_id, contract_id, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.get("/economy/reputation")
async def economy_reputation():
    """F19: Retorna a reputação mercantil de cada agente."""
    return {
        "reputation": {
            agent.name: world.economy.trade_reputation.get(agent.id, 0.0)
            for agent in world.agents
        }
    }


@app.get("/agents/{agent_id}/wallet")
async def agent_wallet(agent_id: str):
    """F17: Retorna saldo de moedas e reputação mercantil do agente."""
    agent = next((a for a in world.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agente não encontrado")
    return {
        "agent_id": agent_id,
        "name": agent.name,
        "coins": world.economy.coins.get(agent_id, 0),
        "trade_reputation": round(world.economy.trade_reputation.get(agent_id, 0), 2),
    }

# ═══════════════════════════════════════════════════════════════════════
# F20 — Guerra de Gangues (modo híbrido warfare + economy)
# ═══════════════════════════════════════════════════════════════════════

class GangWarStartRequest(BaseModel):
    max_ticks: int = 500


class SabotageRequest(BaseModel):
    agent_id: str
    target_gang: str


class DepotRequest(BaseModel):
    agent_id: str
    item: str
    qty: int = 1


class BMBuyRequest(BaseModel):
    agent_id: str
    item: str
    qty: int = 1


@app.post("/gangwar/start", dependencies=[Depends(verify_admin_token)])
async def gangwar_start(req: GangWarStartRequest = GangWarStartRequest()):
    """F20: Inicia a Guerra de Gangues. Requer X-Admin-Token e game_mode gangwar/hybrid."""
    if world.game_mode not in ("gangwar", "hybrid"):
        raise HTTPException(
            400,
            "Mundo não está no modo gangwar/hybrid. Faça /reset com game_mode=gangwar ou hybrid.",
        )
    world.gangwar.start(max_ticks=req.max_ticks)
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🏴‍☠️ Guerra de Gangues iniciada! Máx: {req.max_ticks} ticks"}]
    })
    return {"status": "started", "gangwar": world.gangwar.get_state()}


@app.post("/modes/hybrid/start", dependencies=[Depends(verify_admin_token)])
async def hybrid_mode_start(req: GangWarStartRequest = GangWarStartRequest()):
    """F20: Alias da feature para iniciar GangWar quando o mundo está em modo hybrid."""
    if world.game_mode != "hybrid":
        raise HTTPException(400, "Mundo não está no modo hybrid. Faça /reset com game_mode=hybrid.")
    return await gangwar_start(req)


@app.post("/gangwar/stop", dependencies=[Depends(verify_admin_token)])
async def gangwar_stop():
    """F20: Encerra a Guerra de Gangues."""
    result = world.gangwar.stop()
    await manager.broadcast({
        "type": "update", "data": world.get_state(),
        "events": [{"action": "busy", "event_msg": f"🏆 Gangue {result.get('winner_gang', '?').upper()} venceu a guerra!"}]
    })
    return {"status": "stopped", "result": result}


@app.post("/modes/hybrid/stop", dependencies=[Depends(verify_admin_token)])
async def hybrid_mode_stop():
    """F20: Alias da feature para encerrar GangWar no modo hybrid."""
    if world.game_mode != "hybrid":
        raise HTTPException(400, "Mundo não está no modo hybrid. Faça /reset com game_mode=hybrid.")
    return await gangwar_stop()


@app.get("/gangwar/state")
async def gangwar_state():
    """F20: Retorna o estado completo da Guerra de Gangues."""
    return {"game_mode": world.game_mode, "ticks": world.ticks, "gangwar": world.gangwar.get_state()}


@app.get("/modes/hybrid/state")
async def hybrid_mode_state():
    """F20: Alias da feature para leitura de estado do modo hybrid."""
    if world.game_mode != "hybrid":
        raise HTTPException(400, "Mundo não está no modo hybrid. Faça /reset com game_mode=hybrid.")
    return await gangwar_state()


@app.post("/gangwar/sabotage")
async def gangwar_sabotage(req: SabotageRequest):
    """F20: Agente sabota o depósito da gangue inimiga."""
    events = []
    result = world.gangwar.sabotage_depot(req.agent_id, req.target_gang, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.post("/gangwar/depot/deposit")
async def gangwar_depot_deposit(req: DepotRequest):
    """F20: Agente deposita item no depósito da própria gangue."""
    result = world.gangwar.deposit_item(req.agent_id, req.item, req.qty)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/gangwar/depot/withdraw")
async def gangwar_depot_withdraw(req: DepotRequest):
    """F20: Agente retira item do depósito da própria gangue."""
    result = world.gangwar.withdraw_item(req.agent_id, req.item, req.qty)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/gangwar/depot/{gang}")
async def gangwar_depot_state(gang: str):
    """F20: Retorna estado do depósito de uma gangue."""
    if gang not in ["alpha", "beta"]:
        raise HTTPException(400, "Gangue deve ser 'alpha' ou 'beta'")
    locked_until = world.gangwar.depot_locked_until.get(gang, 0)
    return {
        "gang": gang,
        "depot": world.gangwar.depots.get(gang, {}),
        "locked": locked_until > world.ticks,
        "locked_until_tick": locked_until,
    }


@app.post("/gangwar/black-market/buy")
async def gangwar_bm_buy(req: BMBuyRequest):
    """F20: Agente compra item no mercado negro (preços voláteis, sem rastreio)."""
    events = []
    result = world.gangwar.bm_buy(req.agent_id, req.item, req.qty, events)
    if "error" in result:
        raise HTTPException(400, result["error"])
    if events:
        await manager.broadcast({"type": "update", "data": world.get_state(), "events": events})
    return result


@app.get("/gangwar/black-market/prices")
async def gangwar_bm_prices():
    """F20: Retorna preços e estoque atual do mercado negro."""
    return {
        "prices": world.gangwar.bm_prices,
        "stock": world.gangwar.bm_stock,
        "items": world.gangwar.BLACK_MARKET_ITEMS if hasattr(world.gangwar, 'BLACK_MARKET_ITEMS') else list(world.gangwar.bm_prices),
    }

# ── F11 — Webhooks: Histórico e Estatísticas ─────────────────────────────────

@app.get("/webhooks/admin/history")
async def webhooks_history(
    webhook_id: Optional[str] = None,
    limit: int = 50,
    _: None = Depends(verify_admin_token)
):
    """F11: Retorna histórico de entregas de webhooks (admin). Filtrável por webhook_id."""
    history = webhook_manager.get_delivery_history(webhook_id=webhook_id, limit=limit)
    return {"count": len(history), "deliveries": history}


@app.get("/webhooks/admin/stats")
async def webhooks_stats(_: None = Depends(verify_admin_token)):
    """F11: Retorna estatísticas gerais de disparo de webhooks (admin)."""
    return webhook_manager.get_delivery_stats()


@app.get("/webhooks/admin/event-types")
async def webhooks_events():
    """F11: Lista todos os tipos de evento suportados para registro de webhooks."""
    from storage.webhook_manager import VALID_EVENTS
    return {"valid_events": sorted(VALID_EVENTS)}
