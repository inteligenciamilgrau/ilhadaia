"""
F12 — GincanaEngine
Motor de regras para o Modo Gincana.

Regras:
1. Há 4 checkpoints espalhados pelo mapa. Cada agente captura um checkpoint
   simplesmente chegando até ele (dentro do raio de 1 tile).
2. Um artefato central pode ser coletado por qualquer agente.
3. O agente que carrega o artefato deve entregá-lo à Delivery Zone para marcar um ponto.
4. Cada checkpoint capturado vale 5 pts; cada entrega vale 20 pts.
5. O modo pode ter um timer global (em ticks) — ao esgotar, quem tiver mais pontos vence.
"""
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("BBB_IA.GincanaEngine")

CHECKPOINT_RADIUS = 1            # Tiles de raio para captura de checkpoint
ARTIFACT_PICKUP_RADIUS = 1       # Tiles de raio para pegar artefato
DELIVERY_RADIUS = 2              # Tiles de raio para entregar artefato
CHECKPOINT_SCORE = 5.0           # Pontos por checkpoint
DELIVERY_SCORE = 20.0            # Pontos por entrega
DEFAULT_GINCANA_TICKS = 400      # Duração padrão da gincana


class GincanaEngine:
    """Motor principal do Modo Gincana. Deve ser instanciado pelo World quando game_mode == 'gincana'."""

    def __init__(self, world):
        self.world = world
        self.active: bool = False
        self.max_ticks: int = DEFAULT_GINCANA_TICKS
        self.start_tick: int = 0
        self.gincana_scores: Dict[str, float] = {}  # agent_id → pontuação gincana
        self.checkpoints_captured: Dict[str, Optional[str]] = {}  # checkpoint_id → agent_id (ou None)
        self.artifact_holder: Optional[str] = None   # agent_id carregando o artefato
        self.deliveries: List[Dict] = []             # log de entregas
        self.winner: Optional[str] = None           # agent_id do vencedor
        logger.info("GincanaEngine initialized")

    # ─── Controle de sessão ───────────────────────────────────────────────────

    def start(self, max_ticks: int = DEFAULT_GINCANA_TICKS) -> None:
        """Inicia a gincana."""
        self.active = True
        self.start_tick = self.world.ticks
        self.max_ticks = max_ticks
        self.winner = None
        # Reset scores
        self.gincana_scores = {a.id: 0.0 for a in self.world.agents}
        # Descobre checkpoints no mapa
        self.checkpoints_captured = {
            eid: None for eid, e in self.world.entities.items()
            if e.get("type") == "checkpoint"
        }
        logger.info(f"Gincana started at tick {self.start_tick} (max_ticks={max_ticks}, checkpoints={len(self.checkpoints_captured)})")

    def stop(self) -> Dict:
        """Encerra a gincana e retorna o resultado final."""
        self.active = False
        if not self.gincana_scores:
            return {"winner": None, "scores": {}}
        # Determina vencedor
        winner_id = max(self.gincana_scores, key=self.gincana_scores.get)
        self.winner = winner_id
        winner_agent = next((a for a in self.world.agents if a.id == winner_id), None)
        winner_name = winner_agent.name if winner_agent else winner_id
        logger.info(f"Gincana ended. Winner: {winner_name} ({self.gincana_scores[winner_id]} pts)")
        return {
            "winner_id": winner_id,
            "winner_name": winner_name,
            "scores": self.gincana_scores,
            "deliveries": len(self.deliveries),
        }

    def remaining_ticks(self) -> int:
        if not self.active:
            return 0
        return max(0, self.max_ticks - (self.world.ticks - self.start_tick))

    # ─── Tick principal ───────────────────────────────────────────────────────

    def tick(self, events: list) -> None:
        """Executado a cada tick do world quando gincana está ativa."""
        if not self.active:
            return

        # 1. Verifica timer
        if self.remaining_ticks() == 0:
            result = self.stop()
            events.append({
                "agent_id": result.get("winner_id"),
                "name": result.get("winner_name"),
                "action": "gincana_end",
                "event_msg": f"🏆 Gincana encerrada! Vencedor: {result.get('winner_name')} com {result['scores'].get(result.get('winner_id', ''), 0):.0f} pts!"
            })
            return

        # 2. Verifica capturas e interações para cada agente vivo
        for agent in self.world.agents:
            if not agent.is_alive:
                continue
            self._check_checkpoint_capture(agent, events)
            self._check_artifact_pickup(agent, events)
            self._check_artifact_delivery(agent, events)

    # ─── Mecânicas ────────────────────────────────────────────────────────────

    def _check_checkpoint_capture(self, agent, events: list) -> None:
        for cp_id, captured_by in list(self.checkpoints_captured.items()):
            if captured_by is not None:
                continue  # já capturado
            cp = self.world.entities.get(cp_id)
            if not cp:
                continue
            dist = abs(agent.x - cp["x"]) + abs(agent.y - cp["y"])
            if dist <= CHECKPOINT_RADIUS:
                self.checkpoints_captured[cp_id] = agent.id
                self.gincana_scores[agent.id] = self.gincana_scores.get(agent.id, 0.0) + CHECKPOINT_SCORE
                agent.benchmark["score"] = agent.benchmark.get("score", 0) + CHECKPOINT_SCORE
                # Marcar no mapa
                cp["captured"] = True
                cp["captured_by"] = agent.name
                events.append({
                    "agent_id": agent.id,
                    "name": agent.name,
                    "action": "checkpoint_captured",
                    "event_msg": f"🏁 {agent.name} capturou {cp.get('name', cp_id)}! (+{CHECKPOINT_SCORE:.0f} pts)"
                })
                logger.info(f"Gincana: {agent.name} captured {cp_id} (+{CHECKPOINT_SCORE})")

    def _check_artifact_pickup(self, agent, events: list) -> None:
        """Agente sem artefato pode pegar o artefato se estiver próximo e ninguém o tiver."""
        if self.artifact_holder is not None:
            return  # já está com alguém
        artifact = self.world.entities.get("artifact_main")
        if not artifact or artifact.get("collected"):
            return
        dist = abs(agent.x - artifact["x"]) + abs(agent.y - artifact["y"])
        if dist <= ARTIFACT_PICKUP_RADIUS:
            self.artifact_holder = agent.id
            artifact["collected"] = True
            artifact["holder"] = agent.name
            events.append({
                "agent_id": agent.id,
                "name": agent.name,
                "action": "artifact_picked",
                "event_msg": f"💎 {agent.name} pegou o Artefato Principal!"
            })
            logger.info(f"Gincana: {agent.name} picked artifact")

    def _check_artifact_delivery(self, agent, events: list) -> None:
        """Agente portando o artefato entrega na Delivery Zone."""
        if self.artifact_holder != agent.id:
            return
        delivery = self.world.entities.get("delivery_zone")
        if not delivery:
            return
        dist = abs(agent.x - delivery["x"]) + abs(agent.y - delivery["y"])
        if dist <= DELIVERY_RADIUS:
            # Entrega!
            self.artifact_holder = None
            artifact = self.world.entities.get("artifact_main")
            if artifact:
                artifact["collected"] = False
                artifact["holder"] = None
                # Respawna artefato no centro do mapa
                cx, cy = self.world.size // 2, self.world.size // 2
                artifact["x"] = cx + (len(self.deliveries) % 3) - 1
                artifact["y"] = cy + (len(self.deliveries) // 3) - 1
            score = DELIVERY_SCORE
            self.gincana_scores[agent.id] = self.gincana_scores.get(agent.id, 0.0) + score
            agent.benchmark["score"] = agent.benchmark.get("score", 0) + score
            delivery_record = {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "tick": self.world.ticks,
                "score": score,
            }
            self.deliveries.append(delivery_record)
            events.append({
                "agent_id": agent.id,
                "name": agent.name,
                "action": "artifact_delivered",
                "event_msg": f"🎯 {agent.name} entregou o Artefato! (+{score:.0f} pts)"
            })
            logger.info(f"Gincana: {agent.name} delivered artifact (+{score})")

    # ─── Serialização ─────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """Retorna o estado atual da gincana para incluir no payload do world."""
        return {
            "active": self.active,
            "remaining_ticks": self.remaining_ticks(),
            "max_ticks": self.max_ticks,
            "scores": self.gincana_scores,
            "checkpoints": {
                cp_id: {"captured": cap is not None, "by": cap}
                for cp_id, cap in self.checkpoints_captured.items()
            },
            "artifact_holder": self.artifact_holder,
            "deliveries": len(self.deliveries),
            "winner": self.winner,
        }
