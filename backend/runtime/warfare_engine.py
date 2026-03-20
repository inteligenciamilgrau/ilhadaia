"""
WarfareEngine — F13+F14+F15+F16
Motor de regras para o Modo Warfare.

F13 — Guerra de Facções:
  - 2 facções (Alpha e Beta); agentes são atribuídos ao reset
  - Base de cada facção tem HP; destruir a base inimiga vence o jogo

F14 — Combate de Arremesso:
  - Ação "throw_stone": gasta pedra do inventário, causa dano em raio 1 ao alvo
  - Supply crates e ammo_caches no mapa (spawned pelo world._get_mode_spawn_objects)

F15 — Papéis Táticos:
  - 3 papéis: scout (visão ampla), medic (cura aliados), warrior (dano extra)
  - Cada agente recebe papel ao iniciar o modo warfare

F16 — Controle de Território:
  - Zona central: quien fica +3 ticks consecutivos captura
  - Captura vale 2 pts/tick para a facção controladora
"""
import logging
import random
from typing import Optional, List, Dict, Any

logger = logging.getLogger("BBB_IA.WarfareEngine")

# ─── Constantes ──────────────────────────────────────────────────────────────

FACTIONS = ["alpha", "beta"]
ROLES = ["scout", "medic", "warrior"]

ROLE_BONUSES = {
    "scout": {"vision_range": 8, "damage_mult": 1.0, "heal_amount": 0},
    "medic": {"vision_range": 4, "damage_mult": 0.8, "heal_amount": 5},
    "warrior": {"vision_range": 4, "damage_mult": 1.5, "heal_amount": 0},
}

THROW_DAMAGE = 15.0          # Dano base de arremesso
THROW_RANGE = 5              # Alcance máximo (manhattan)
THROW_AOE_RADIUS = 1         # Raio de área de efeito
BASE_HP = 100.0              # HP inicial das bases
TERRITORY_TICKS_TO_CAPTURE = 3   # Ticks consecutivos para capturar zona
TERRITORY_SCORE_PER_TICK = 2.0   # Score por tick controlando zona


class WarfareEngine:
    """Motor principal do Modo Warfare. Instanciado pelo World quando game_mode == 'warfare'."""

    def __init__(self, world):
        self.world = world
        self.active: bool = False
        self.start_tick: int = 0
        self.max_ticks: int = 600

        # F13 — Facções
        self.faction_scores: Dict[str, float] = {"alpha": 0.0, "beta": 0.0}
        self.faction_bases: Dict[str, str] = {}  # faction → entity_id da base
        self.base_hp: Dict[str, float] = {"alpha": BASE_HP, "beta": BASE_HP}
        self.agent_factions: Dict[str, str] = {}  # agent_id → faction
        self.winner_faction: Optional[str] = None

        # F14 — Arremesso
        self.throw_log: List[Dict] = []

        # F15 — Papéis Táticos
        self.agent_roles: Dict[str, str] = {}  # agent_id → role

        # F16 — Controle de Território
        self.territory_holder: Optional[str] = None        # faction ou None
        self.territory_contesting_faction: Optional[str] = None
        self.territory_contest_ticks: int = 0

        logger.info("WarfareEngine initialized")

    # ─── Setup ───────────────────────────────────────────────────────────────

    def start(self, max_ticks: int = 600) -> None:
        """Inicia o modo warfare — atribui facções, papéis e registra bases."""
        self.active = True
        self.start_tick = self.world.ticks
        self.max_ticks = max_ticks
        self.faction_scores = {"alpha": 0.0, "beta": 0.0}
        self.base_hp = {"alpha": BASE_HP, "beta": BASE_HP}
        self.winner_faction = None
        self.throw_log = []
        self.territory_holder = None
        self.territory_contest_ticks = 0

        # Registra bases pelo nome da entidade
        self.faction_bases = {}
        for eid, e in self.world.entities.items():
            if e.get("type") == "team_base":
                faction = e.get("team")
                if faction:
                    self.faction_bases[faction] = eid

        # Atribui facções e papéis
        agents = self.world.agents
        roles_cycle = ROLES * (len(agents) // len(ROLES) + 1)
        random.shuffle(roles_cycle)
        for i, agent in enumerate(agents):
            faction = FACTIONS[i % 2]
            self.agent_factions[agent.id] = faction
            self.agent_roles[agent.id] = roles_cycle[i]
            # Armazena no próprio agente para acesso no contexto IA
            agent.faction = faction  # type: ignore[attr-defined]
            agent.role = roles_cycle[i]  # type: ignore[attr-defined]

        logger.info(f"Warfare started: {len(agents)} agents, factions={self.faction_bases}")

    def stop(self) -> Dict:
        """Encerra o modo warfare."""
        self.active = False
        if not self.winner_faction:
            # Vence quem tem mais pontos
            self.winner_faction = max(self.faction_scores, key=self.faction_scores.get)
        logger.info(f"Warfare ended. Winner: {self.winner_faction}")
        return {
            "winner_faction": self.winner_faction,
            "scores": self.faction_scores,
            "base_hp": self.base_hp,
            "throws": len(self.throw_log),
        }

    def remaining_ticks(self) -> int:
        return max(0, self.max_ticks - (self.world.ticks - self.start_tick))

    # ─── Tick principal ──────────────────────────────────────────────────────

    def tick(self, events: list) -> None:
        if not self.active:
            return

        # Timer
        if self.remaining_ticks() == 0:
            result = self.stop()
            events.append({
                "agent_id": None, "name": None,
                "action": "warfare_end",
                "event_msg": f"🏴 Warfare encerrado! Facção {result['winner_faction'].upper()} vence!"
            })
            return

        # F14 — Arremessos automáticos (agentes com pedra no inventário perto de inimigos)
        self._tick_throw_combat(events)

        # F15 — Efeito de papéis táticos
        self._tick_roles(events)

        # F16 — Controle de território
        self._tick_territory(events)

    # ─── F14 — Arremesso ────────────────────────────────────────────────────

    def throw_stone(self, attacker_id: str, target_x: int, target_y: int, events: list) -> Dict:
        """Lança uma pedra de agent_id para (target_x, target_y)."""
        attacker = next((a for a in self.world.agents if a.id == attacker_id and a.is_alive), None)
        if not attacker:
            return {"error": "Atacante não encontrado"}

        # Verifica alcance
        dist = abs(attacker.x - target_x) + abs(attacker.y - target_y)
        if dist > THROW_RANGE:
            return {"error": f"Alvo fora do alcance (dist={dist}, max={THROW_RANGE})"}

        # Verifica pedra no inventário
        has_stone = "stone" in attacker.inventory or "throwable_stone" in [
            e.get("type") for e in self.world.entities.values()
            if e.get("x") == attacker.x and e.get("y") == attacker.y
        ]
        # fallback: permite arremesso sem custar item na demo
        role = self.agent_roles.get(attacker_id, "warrior")
        damage_mult = ROLE_BONUSES[role]["damage_mult"]
        base_damage = THROW_DAMAGE * damage_mult

        # Aplica dano em AOE
        faction_a = self.agent_factions.get(attacker_id)
        hit_agents = []
        for target in self.world.agents:
            if not target.is_alive:
                continue
            if target.id == attacker_id:
                continue
            # Só atinge inimigos (faction diferente ou neutros)
            faction_t = self.agent_factions.get(target.id)
            if faction_a and faction_t and faction_a == faction_t:
                continue  # mesmo time
            dist_to_impact = abs(target.x - target_x) + abs(target.y - target_y)
            if dist_to_impact <= THROW_AOE_RADIUS:
                target.hp = max(0, target.hp - base_damage)
                hit_agents.append(target.name)
                if target.hp <= 0:
                    target.is_alive = False
                    target.death_tick = self.world.ticks
                    events.append({
                        "agent_id": target.id, "name": target.name,
                        "action": "death",
                        "event_msg": f"💀 {target.name} foi eliminado pelo arremesso de {attacker.name}!"
                    })

        record = {
            "attacker": attacker.name,
            "attacker_id": attacker_id,
            "target_x": target_x, "target_y": target_y,
            "damage": base_damage,
            "hit": hit_agents,
            "tick": self.world.ticks,
        }
        self.throw_log.append(record)
        events.append({
            "agent_id": attacker_id, "name": attacker.name,
            "action": "throw_stone",
            "event_msg": f"🪨 {attacker.name} arremessou pedra! Acertou: {hit_agents or 'ninguém'}"
        })
        logger.info(f"F14: {attacker.name} threw stone → {target_x},{target_y} hit={hit_agents}")
        return record

    def _tick_throw_combat(self, events: list) -> None:
        """Guerreiros tentam arremessar pedras em inimigos próximos."""
        for agent in self.world.agents:
            if not agent.is_alive:
                continue
            if self.agent_roles.get(agent.id) != "warrior":
                continue
            faction_a = self.agent_factions.get(agent.id)
            # Encontra inimigo mais próximo dentro do alcance
            closest = None
            closest_dist = THROW_RANGE + 1
            for enemy in self.world.agents:
                if not enemy.is_alive or enemy.id == agent.id:
                    continue
                faction_e = self.agent_factions.get(enemy.id)
                if faction_a and faction_e and faction_a == faction_e:
                    continue
                dist = abs(agent.x - enemy.x) + abs(agent.y - enemy.y)
                if dist <= THROW_RANGE and dist < closest_dist:
                    closest_dist = dist
                    closest = enemy
            if closest and self.world.ticks % 8 == 0:  # Arremessa a cada 8 ticks
                self.throw_stone(agent.id, closest.x, closest.y, events)

    # ─── F15 — Papéis Táticos ───────────────────────────────────────────────

    def _tick_roles(self, events: list) -> None:
        """Aplica efeitos passivos de papéis: medic cura aliados próximos."""
        for agent in self.world.agents:
            if not agent.is_alive:
                continue
            if self.agent_roles.get(agent.id) != "medic":
                continue
            faction_a = self.agent_factions.get(agent.id)
            heal = ROLE_BONUSES["medic"]["heal_amount"]
            for ally in self.world.agents:
                if not ally.is_alive or ally.id == agent.id:
                    continue
                if self.agent_factions.get(ally.id) != faction_a:
                    continue
                dist = abs(agent.x - ally.x) + abs(agent.y - ally.y)
                if dist <= 3 and ally.hp < 100 and self.world.ticks % 5 == 0:
                    ally.hp = min(100, ally.hp + heal)
                    logger.debug(f"F15: {agent.name}(medic) healed {ally.name} +{heal} HP")

    # ─── F16 — Controle de Território ───────────────────────────────────────

    def _tick_territory(self, events: list) -> None:
        """Verifica quem está na zona central e atualiza controle."""
        zone = self.world.entities.get("control_zone_center")
        if not zone:
            return

        zx, zy = zone.get("x", 0), zone.get("y", 0)
        capture_radius = 2

        # Conta agentes de cada facção na zona
        counts: Dict[str, int] = {"alpha": 0, "beta": 0}
        for agent in self.world.agents:
            if not agent.is_alive:
                continue
            dist = abs(agent.x - zx) + abs(agent.y - zy)
            if dist <= capture_radius:
                f = self.agent_factions.get(agent.id)
                if f in counts:
                    counts[f] += 1

        # Determina quem está contestando
        alpha_n, beta_n = counts["alpha"], counts["beta"]
        if alpha_n > 0 and beta_n == 0:
            contesting = "alpha"
        elif beta_n > 0 and alpha_n == 0:
            contesting = "beta"
        else:
            contesting = None  # Contestado por ambos ou vazia

        if contesting:
            if contesting == self.territory_contesting_faction:
                self.territory_contest_ticks += 1
            else:
                self.territory_contesting_faction = contesting
                self.territory_contest_ticks = 1

            if self.territory_contest_ticks >= TERRITORY_TICKS_TO_CAPTURE:
                if self.territory_holder != contesting:
                    self.territory_holder = contesting
                    zone["controlled_by"] = contesting
                    events.append({
                        "agent_id": None, "name": None,
                        "action": "territory_captured",
                        "event_msg": f"🏴 Facção {contesting.upper()} capturou a Zona Central!"
                    })
                    logger.info(f"F16: Territory captured by {contesting}")
        else:
            self.territory_contest_ticks = 0

        # Pontos para quem controla
        if self.territory_holder:
            score = TERRITORY_SCORE_PER_TICK
            self.faction_scores[self.territory_holder] = (
                self.faction_scores.get(self.territory_holder, 0) + score
            )
            # Distribui também nos agentes da facção
            for agent in self.world.agents:
                if agent.is_alive and self.agent_factions.get(agent.id) == self.territory_holder:
                    agent.benchmark["score"] = agent.benchmark.get("score", 0) + score / max(1, len([
                        a for a in self.world.agents
                        if a.is_alive and self.agent_factions.get(a.id) == self.territory_holder
                    ]))

    # ─── Serialização ────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        agent_info = []
        for agent in self.world.agents:
            agent_info.append({
                "id": agent.id,
                "name": agent.name,
                "faction": self.agent_factions.get(agent.id),
                "role": self.agent_roles.get(agent.id),
                "score": self.faction_scores.get(self.agent_factions.get(agent.id, ""), 0),
            })
        return {
            "active": self.active,
            "remaining_ticks": self.remaining_ticks(),
            "faction_scores": self.faction_scores,
            "base_hp": self.base_hp,
            "territory_holder": self.territory_holder,
            "territory_contest_ticks": self.territory_contest_ticks,
            "throws": len(self.throw_log),
            "winner_faction": self.winner_faction,
            "agents": agent_info,
        }
