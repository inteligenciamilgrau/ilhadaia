"""
GangWarEngine — F20 Guerra de Gangues
Modo híbrido: Warfare (facções/combate) + Economy (mercado negro, depósitos, sabotagem).

Mecânicas:
- Gangues Alpha e Beta combatem pelo controle de pontos de recurso
- Black Market: itens vendidos/comprados sem rastreio, preços voláteis
- Sabotagem: agente pode sabotar o depósito inimigo, travando recursos por N ticks
- Depot: cada gangue tem um depósito de recursos compartilhado
- Conquista de supply_posts: gera renda passiva para a gangue controladora
"""
import logging
import random
from typing import Optional, List, Dict, Any

logger = logging.getLogger("BBB_IA.GangWarEngine")

# ─── Constantes ──────────────────────────────────────────────────────────────

GANGS = ["alpha", "beta"]
DEPOT_CAPACITY = 50              # Itens máximos no depósito
SABOTAGE_LOCKOUT_TICKS = 15      # Ticks que o depósito fica bloqueado após sabotagem
SUPPLY_POST_INCOME_INTERVAL = 10 # Ticks entre renda passiva de supply_posts
SUPPLY_POST_INCOME = 3.0         # Recursos gerados por supply_post controlado por ciclo

BLACK_MARKET_ITEMS = ["axe", "ammo_pack", "disguise_kit", "explosive", "medkit"]
BLACK_MARKET_VOLATILITY = 0.4    # Oscilação máxima ±40% do preço base

_BM_BASE_PRICES: Dict[str, float] = {
    "axe": 12.0,
    "ammo_pack": 8.0,
    "disguise_kit": 15.0,
    "explosive": 20.0,
    "medkit": 10.0,
}


class GangWarEngine:
    def __init__(self, world):
        self.world = world
        self.active: bool = False
        self.start_tick: int = 0
        self.max_ticks: int = 500

        # Gangues
        self.gang_scores: Dict[str, float] = {"alpha": 0.0, "beta": 0.0}
        self.agent_gangs: Dict[str, str] = {}       # agent_id → gang
        self.winner_gang: Optional[str] = None

        # Depósitos de recursos
        self.depots: Dict[str, Dict[str, int]] = {
            "alpha": {},
            "beta": {},
        }
        self.depot_locked_until: Dict[str, int] = {"alpha": 0, "beta": 0}

        # Supply posts
        self.supply_posts: Dict[str, Optional[str]] = {}  # entity_id → gang ou None

        # Mercado negro
        self.bm_prices: Dict[str, float] = dict(_BM_BASE_PRICES)
        self.bm_stock: Dict[str, int] = {k: random.randint(2, 8) for k in BLACK_MARKET_ITEMS}
        self.bm_tx_log: List[Dict] = []

        # Log de sabotagens
        self.sabotage_log: List[Dict] = []

        logger.info("GangWarEngine initialized")

    # ─── Setup ───────────────────────────────────────────────────────────────

    def start(self, max_ticks: int = 500) -> None:
        self.active = True
        self.start_tick = self.world.ticks
        self.max_ticks = max_ticks
        self.gang_scores = {"alpha": 0.0, "beta": 0.0}
        self.winner_gang = None
        self.depots = {"alpha": {}, "beta": {}}
        self.depot_locked_until = {"alpha": 0, "beta": 0}
        self.bm_prices = dict(_BM_BASE_PRICES)
        self.bm_stock = {k: random.randint(2, 8) for k in BLACK_MARKET_ITEMS}
        self.bm_tx_log = []
        self.sabotage_log = []

        # Atribuir gangues alternadamente
        for i, agent in enumerate(self.world.agents):
            gang = GANGS[i % 2]
            self.agent_gangs[agent.id] = gang
            agent.faction = gang  # compatível com warfare

        # Registrar supply_posts
        self.supply_posts = {
            eid: None for eid, e in self.world.entities.items()
            if e.get("type") == "supply_post"
        }

        logger.info(f"GangWar started: {len(self.world.agents)} agents, {len(self.supply_posts)} supply posts")

    def stop(self) -> Dict:
        self.active = False
        if not self.winner_gang:
            self.winner_gang = max(self.gang_scores, key=self.gang_scores.get)
        logger.info(f"GangWar ended. Winner: {self.winner_gang}")
        return {
            "winner_gang": self.winner_gang,
            "scores": self.gang_scores,
            "depots": self.depots,
            "sabotages": len(self.sabotage_log),
            "bm_transactions": len(self.bm_tx_log),
        }

    def remaining_ticks(self) -> int:
        return max(0, self.max_ticks - (self.world.ticks - self.start_tick))

    # ─── Tick principal ──────────────────────────────────────────────────────

    def tick(self, events: list) -> None:
        if not self.active:
            return

        if self.remaining_ticks() == 0:
            result = self.stop()
            events.append({
                "action": "gangwar_end",
                "event_msg": f"🏴‍☠️ Guerra de Gangues encerrada! Gangue {result['winner_gang'].upper()} vence!"
            })
            return

        # Renda passiva dos supply_posts
        if self.world.ticks % SUPPLY_POST_INCOME_INTERVAL == 0:
            self._tick_supply_income(events)

        # Captura de supply_posts por agentes próximos
        self._tick_supply_capture(events)

        # Volatilidade do mercado negro
        if self.world.ticks % 15 == 0:
            self._fluctuate_bm_prices()

    # ─── Supply Posts ────────────────────────────────────────────────────────

    def _tick_supply_capture(self, events: list) -> None:
        for sp_id, holding_gang in list(self.supply_posts.items()):
            sp = self.world.entities.get(sp_id)
            if not sp:
                continue
            # Conta agentes de cada gangue em raio 2
            counts: Dict[str, int] = {"alpha": 0, "beta": 0}
            for agent in self.world.agents:
                if not agent.is_alive:
                    continue
                dist = abs(agent.x - sp["x"]) + abs(agent.y - sp["y"])
                if dist <= 2:
                    g = self.agent_gangs.get(agent.id)
                    if g in counts:
                        counts[g] += 1
            # Captura se uma gangue domina sozinha
            if counts["alpha"] > 0 and counts["beta"] == 0:
                captor = "alpha"
            elif counts["beta"] > 0 and counts["alpha"] == 0:
                captor = "beta"
            else:
                continue
            if holding_gang != captor:
                self.supply_posts[sp_id] = captor
                sp["controlled_by"] = captor
                events.append({
                    "action": "supply_captured",
                    "event_msg": f"📦 Gangue {captor.upper()} capturou supply post!"
                })

    def _tick_supply_income(self, events: list) -> None:
        income_by_gang: Dict[str, int] = {"alpha": 0, "beta": 0}
        for gang in self.supply_posts.values():
            if gang:
                income_by_gang[gang] = income_by_gang.get(gang, 0) + 1

        for gang, count in income_by_gang.items():
            if count == 0:
                continue
            item = "apple"
            earned = count
            self.depots[gang][item] = self.depots[gang].get(item, 0) + earned
            self.gang_scores[gang] += earned * SUPPLY_POST_INCOME
            if earned > 0:
                events.append({
                    "action": "depot_income",
                    "event_msg": f"💼 Gangue {gang.upper()}: +{earned} {item} no depósito ({count} posts)"
                })

    # ─── Sabotagem ───────────────────────────────────────────────────────────

    def sabotage_depot(self, agent_id: str, target_gang: str, events: list) -> Dict:
        """Agente sabota o depósito da gangue inimiga, travando-o por N ticks."""
        agent = next((a for a in self.world.agents if a.id == agent_id and a.is_alive), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        attacker_gang = self.agent_gangs.get(agent_id)
        if attacker_gang == target_gang:
            return {"error": "Não pode sabotar o próprio depósito"}
        if self.depot_locked_until.get(target_gang, 0) > self.world.ticks:
            left = self.depot_locked_until[target_gang] - self.world.ticks
            return {"error": f"Depósito já sabotado ({left} ticks restantes)"}

        self.depot_locked_until[target_gang] = self.world.ticks + SABOTAGE_LOCKOUT_TICKS
        # Perde alguns recursos do depósito
        lost = {}
        for item in list(self.depots[target_gang]):
            qty = self.depots[target_gang][item]
            drop = max(1, qty // 3)
            self.depots[target_gang][item] = qty - drop
            lost[item] = drop

        record = {
            "saboteur": agent.name, "agent_id": agent_id,
            "target_gang": target_gang, "tick": self.world.ticks,
            "resources_lost": lost,
        }
        self.sabotage_log.append(record)
        events.append({
            "agent_id": agent_id, "name": agent.name,
            "action": "sabotage",
            "event_msg": f"💥 {agent.name} sabotou o depósito de {target_gang.upper()}! -{SABOTAGE_LOCKOUT_TICKS} ticks bloqueado"
        })
        logger.info(f"F20: {agent.name} sabotaged {target_gang} depot")
        return record

    # ─── Depósito ────────────────────────────────────────────────────────────

    def deposit_item(self, agent_id: str, item: str, qty: int) -> Dict:
        """Agente deposita item no depósito da sua gangue."""
        agent = next((a for a in self.world.agents if a.id == agent_id), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        gang = self.agent_gangs.get(agent_id)
        if not gang:
            return {"error": "Agente sem gangue"}
        if self.depot_locked_until.get(gang, 0) > self.world.ticks:
            return {"error": "Depósito bloqueado por sabotagem"}
        owned = agent.inventory.count(item)
        if owned < qty:
            return {"error": f"Inventário insuficiente: {owned}x {item}"}
        total = sum(self.depots[gang].values())
        if total + qty > DEPOT_CAPACITY:
            return {"error": f"Depósito cheio ({total}/{DEPOT_CAPACITY})"}

        for _ in range(qty):
            agent.inventory.remove(item)
        self.depots[gang][item] = self.depots[gang].get(item, 0) + qty
        return {"status": "deposited", "gang": gang, "item": item, "qty": qty,
                "depot": self.depots[gang]}

    def withdraw_item(self, agent_id: str, item: str, qty: int) -> Dict:
        """Agente retira item do depósito da sua gangue."""
        agent = next((a for a in self.world.agents if a.id == agent_id), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        gang = self.agent_gangs.get(agent_id)
        if not gang:
            return {"error": "Agente sem gangue"}
        if self.depot_locked_until.get(gang, 0) > self.world.ticks:
            return {"error": "Depósito bloqueado por sabotagem"}
        available = self.depots[gang].get(item, 0)
        if available < qty:
            return {"error": f"Depósito tem apenas {available}x {item}"}

        self.depots[gang][item] = available - qty
        for _ in range(qty):
            agent.inventory.append(item)
        return {"status": "withdrawn", "gang": gang, "item": item, "qty": qty,
                "depot": self.depots[gang]}

    # ─── Mercado Negro ───────────────────────────────────────────────────────

    def _fluctuate_bm_prices(self) -> None:
        for item, base in _BM_BASE_PRICES.items():
            delta = random.uniform(-BLACK_MARKET_VOLATILITY, BLACK_MARKET_VOLATILITY)
            self.bm_prices[item] = round(base * (1 + delta), 2)

    def bm_buy(self, agent_id: str, item: str, qty: int, events: list) -> Dict:
        """Agente compra no mercado negro (sem rastreio de gangue)."""
        agent = next((a for a in self.world.agents if a.id == agent_id), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        if item not in self.bm_prices:
            return {"error": f"Item não disponível no mercado negro"}
        stock = self.bm_stock.get(item, 0)
        if stock < qty:
            return {"error": f"Estoque insuficiente: {stock}x {item}"}
        # Usa moedas da economy engine
        cost = self.bm_prices[item] * qty
        agent_coins = self.world.economy.coins.get(agent_id, 0)
        if agent_coins < cost:
            return {"error": f"Moedas insuficientes ({agent_coins:.1f} < {cost:.1f})"}

        self.world.economy.coins[agent_id] = agent_coins - cost
        self.bm_stock[item] -= qty
        for _ in range(qty):
            agent.inventory.append(item)
        tx = {"type": "bm_buy", "agent": agent.name, "item": item, "qty": qty,
              "total": cost, "tick": self.world.ticks}
        self.bm_tx_log.append(tx)
        events.append({
            "agent_id": agent_id, "name": agent.name,
            "action": "bm_buy",
            "event_msg": f"🕵️ {agent.name} comprou {qty}x {item} no mercado negro"
        })
        return tx

    # ─── Estado ──────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "remaining_ticks": self.remaining_ticks(),
            "gang_scores": self.gang_scores,
            "depots": self.depots,
            "depot_locked_until": self.depot_locked_until,
            "supply_posts_controlled": {
                gang: sum(1 for g in self.supply_posts.values() if g == gang)
                for gang in GANGS
            },
            "bm_prices": self.bm_prices,
            "bm_stock": self.bm_stock,
            "sabotages": len(self.sabotage_log),
            "bm_transactions": len(self.bm_tx_log),
            "winner_gang": self.winner_gang,
        }
