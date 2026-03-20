"""
EconomyEngine — F10 + F17 + F18 + F19
Motor de economia e crafting para o modo Economy (e acessível em outros modos).

F10 — Crafting e Construção:
  - Receitas: wood+stone→axe, wood×3→raft, stone×2→wall
  - Ação craft(agent_id, recipe) consome itens do inventário
  - Ação build(agent_id, structure_type, x, y) coloca estrutura no mapa

F17 — Comércio Local entre Agentes:
  - trade(seller_id, buyer_id, item, price_coins) — transfere item por moedas
  - Agentes recebem 10 moedas ao iniciar a sessão

F18 — Mercado Dinâmico com Oferta e Demanda:
  - market_price(item) — preço calculado por escassez/abundância no mapa
  - market_buy(agent_id, item, qty) — compra do mercado central
  - market_sell(agent_id, item, qty) — vende ao mercado central

F19 — Contratos e Reputação Mercantil:
  - post_contract(requester_id, item, qty, reward) — publica contrato
  - fulfill_contract(agent_id, contract_id) — cumpre contrato e paga recompensa
  - trade_reputation por agente (acumula com trade/contratos)
"""
import logging
import random
from typing import Optional, List, Dict, Any

logger = logging.getLogger("BBB_IA.EconomyEngine")

# ─── Constantes ──────────────────────────────────────────────────────────────

STARTING_COINS = 10
MARKET_BASE_PRICES: Dict[str, float] = {
    "apple": 2.0,
    "wood": 3.0,
    "stone": 3.0,
    "water_flask": 4.0,
    "axe": 10.0,
    "raft": 15.0,
    "wall": 8.0,
}
MARKET_STOCK: Dict[str, int] = {
    "apple": 20,
    "wood": 15,
    "stone": 15,
    "water_flask": 10,
    "axe": 5,
    "raft": 3,
    "wall": 6,
}

RECIPES: Dict[str, Dict] = {
    "axe": {
        "ingredients": {"wood": 1, "stone": 1},
        "description": "Machado — derruba árvores mais rápido e aumenta dano",
        "effect": "damage_bonus",
    },
    "raft": {
        "ingredients": {"wood": 3},
        "description": "Jangada — permite cruzar água lentamente",
        "effect": "water_traverse",
    },
    "wall": {
        "ingredients": {"stone": 2},
        "description": "Parede de pedra — cria barricada intransponível",
        "effect": "obstacle",
    },
    "torch": {
        "ingredients": {"wood": 1},
        "description": "Tocha — ilumina a noite e repele zumbis",
        "effect": "night_light",
    },
    "bandage": {
        "ingredients": {"apple": 2},
        "description": "Bandagem improvisada — restaura 20 HP",
        "effect": "heal_20",
    },
}

STRUCTURES = {"wall", "raft"}  # Receitas que se tornam entidades no mapa


class EconomyEngine:
    def __init__(self, world):
        self.world = world
        self.active: bool = False

        # F17 — Carteiras dos agentes
        self.coins: Dict[str, float] = {}          # agent_id → saldo

        # F18 — Estado do mercado
        self.market_stock: Dict[str, int] = dict(MARKET_STOCK)
        self.market_prices: Dict[str, float] = dict(MARKET_BASE_PRICES)
        self.market_tx_log: List[Dict] = []        # log de transações

        # F19 — Contratos
        self.contracts: List[Dict] = []            # contratos abertos
        self.contract_id_seq: int = 0
        self.trade_reputation: Dict[str, float] = {}  # agent_id → rep

        # F10 — crafts realizados
        self.craft_log: List[Dict] = []

        logger.info("EconomyEngine initialized")

    # ─── Setup ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        self.active = True
        self.coins = {a.id: STARTING_COINS for a in self.world.agents}
        self.trade_reputation = {a.id: 0.0 for a in self.world.agents}
        self.market_stock = dict(MARKET_STOCK)
        self.market_prices = dict(MARKET_BASE_PRICES)
        self.contracts = []
        self.craft_log = []
        self.market_tx_log = []
        logger.info(f"EconomyEngine started with {len(self.world.agents)} agents")

    # ─── F10 — Crafting ──────────────────────────────────────────────────────

    def craft(self, agent_id: str, recipe_name: str, events: list) -> Dict:
        """Consome ingredientes do inventário do agente e produz o item craftado."""
        agent = next((a for a in self.world.agents if a.id == agent_id and a.is_alive), None)
        if not agent:
            return {"error": "Agente não encontrado"}

        recipe = RECIPES.get(recipe_name)
        if not recipe:
            return {"error": f"Receita '{recipe_name}' não existe. Válidas: {list(RECIPES)}"}

        # Verifica ingredientes no inventário
        inv_counts: Dict[str, int] = {}
        for item in agent.inventory:
            inv_counts[item] = inv_counts.get(item, 0) + 1

        for ingredient, qty_needed in recipe["ingredients"].items():
            if inv_counts.get(ingredient, 0) < qty_needed:
                return {"error": f"Ingredientes insuficientes: faltam {qty_needed}x {ingredient}"}

        # Consome ingredientes
        for ingredient, qty_needed in recipe["ingredients"].items():
            removed = 0
            new_inv = []
            for item in agent.inventory:
                if item == ingredient and removed < qty_needed:
                    removed += 1
                else:
                    new_inv.append(item)
            agent.inventory = new_inv

        # Aplica efeito
        if recipe["effect"] == "heal_20":
            agent.hp = min(100, agent.hp + 20)
            # Bandagem não deixa item no inventário (é consumida ao usar)
        elif recipe_name in STRUCTURES:
            # Coloca estrutura no mapa próximo ao agente
            sx, sy = (agent.x + 1) % self.world.size, agent.y
            self.world.entities[f"built_{recipe_name}_{self.world.ticks}"] = {
                "type": recipe_name, "x": sx, "y": sy,
                "built_by": agent.name, "tick": self.world.ticks
            }
        else:
            # Adiciona item craftado ao inventário (axe, torch, etc.)
            agent.inventory.append(recipe_name)
            if recipe["effect"] == "damage_bonus":
                agent.benchmark["craft_axe"] = agent.benchmark.get("craft_axe", 0) + 1

        record = {
            "agent_id": agent_id, "agent": agent.name,
            "recipe": recipe_name, "tick": self.world.ticks,
            "ingredients": recipe["ingredients"],
        }
        self.craft_log.append(record)
        events.append({
            "agent_id": agent_id, "name": agent.name,
            "action": "craft",
            "event_msg": f"🔨 {agent.name} craftou {recipe_name}! ({recipe['description']})"
        })
        logger.info(f"F10: {agent.name} crafted {recipe_name}")
        return record

    def build(self, agent_id: str, structure_type: str, x: int, y: int, events: list) -> Dict:
        """Constrói uma estrutura no mapa consumindo item craftado ou ingredientes da receita."""
        agent = next((a for a in self.world.agents if a.id == agent_id and a.is_alive), None)
        if not agent:
            return {"error": "Agente não encontrado"}

        if structure_type not in STRUCTURES:
            return {"error": f"Estrutura inválida '{structure_type}'. Válidas: {sorted(STRUCTURES)}"}

        if not (0 <= x < self.world.size and 0 <= y < self.world.size):
            return {"error": f"Coordenadas fora do mapa ({self.world.size}x{self.world.size})"}

        # Não permitir sobreposição com agentes/estruturas já presentes.
        occupied = any(
            e.get("x") == x and e.get("y") == y and e.get("type") in {"agent", "wall", "raft"}
            for e in self.world.entities.values()
        )
        if occupied:
            return {"error": "Posição ocupada por outra entidade"}

        # Parede exige tile caminhável; jangada exige água.
        tile_types = [
            e.get("type")
            for e in self.world.entities.values()
            if e.get("x") == x and e.get("y") == y
        ]
        if structure_type == "wall":
            if not self.world._is_walkable(x, y):
                return {"error": "Parede só pode ser construída em tile caminhável livre"}
        elif structure_type == "raft":
            if "water" not in tile_types:
                return {"error": "Jangada só pode ser construída em tile de água"}

        consumed_mode = ""
        if structure_type in agent.inventory:
            agent.inventory.remove(structure_type)
            consumed_mode = "crafted_item"
        else:
            recipe = RECIPES.get(structure_type)
            if not recipe:
                return {"error": f"Receita não encontrada para '{structure_type}'"}

            inv_counts: Dict[str, int] = {}
            for item in agent.inventory:
                inv_counts[item] = inv_counts.get(item, 0) + 1

            for ingredient, qty_needed in recipe["ingredients"].items():
                if inv_counts.get(ingredient, 0) < qty_needed:
                    return {"error": f"Ingredientes insuficientes para construir {structure_type}"}

            for ingredient, qty_needed in recipe["ingredients"].items():
                removed = 0
                new_inv = []
                for item in agent.inventory:
                    if item == ingredient and removed < qty_needed:
                        removed += 1
                    else:
                        new_inv.append(item)
                agent.inventory = new_inv
            consumed_mode = "recipe_ingredients"

        entity_id = f"built_{structure_type}_{self.world.ticks}_{x}_{y}"
        self.world.entities[entity_id] = {
            "type": structure_type,
            "x": x,
            "y": y,
            "built_by": agent.name,
            "builder_id": agent.id,
            "tick": self.world.ticks,
        }

        record = {
            "agent_id": agent.id,
            "agent": agent.name,
            "structure": structure_type,
            "x": x,
            "y": y,
            "entity_id": entity_id,
            "consumed": consumed_mode,
            "tick": self.world.ticks,
        }
        events.append({
            "agent_id": agent.id,
            "name": agent.name,
            "action": "build",
            "event_msg": f"🧱 {agent.name} construiu {structure_type} em ({x},{y})"
        })
        logger.info("F10: %s built %s at %s,%s (%s)", agent.name, structure_type, x, y, consumed_mode)
        return record

    # ─── F17 — Comércio entre agentes ────────────────────────────────────────

    def trade(self, seller_id: str, buyer_id: str, item: str, price: float, events: list) -> Dict:
        """Transfere item do seller para buyer por price moedas."""
        seller = next((a for a in self.world.agents if a.id == seller_id), None)
        buyer = next((a for a in self.world.agents if a.id == buyer_id), None)
        if not seller or not buyer:
            return {"error": "Agente(s) não encontrado(s)"}
        if item not in seller.inventory:
            return {"error": f"{seller.name} não tem {item} no inventário"}
        buyer_coins = self.coins.get(buyer_id, 0)
        if buyer_coins < price:
            return {"error": f"{buyer.name} não tem moedas suficientes ({buyer_coins:.1f} < {price})"}

        # Executa
        seller.inventory.remove(item)
        buyer.inventory.append(item)
        self.coins[seller_id] = self.coins.get(seller_id, 0) + price
        self.coins[buyer_id] = buyer_coins - price
        self.trade_reputation[seller_id] = self.trade_reputation.get(seller_id, 0) + 1.0
        self.trade_reputation[buyer_id] = self.trade_reputation.get(buyer_id, 0) + 0.5

        tx = {"seller": seller.name, "seller_id": seller_id,
              "buyer": buyer.name, "buyer_id": buyer_id,
              "item": item, "price": price, "tick": self.world.ticks}
        self.market_tx_log.append(tx)
        events.append({
            "agent_id": seller_id, "name": seller.name,
            "action": "trade",
            "event_msg": f"🤝 {seller.name} vendeu {item} para {buyer.name} por {price:.1f} moedas"
        })
        logger.info(f"F17: trade {item} {seller.name}→{buyer.name} for {price}")
        return tx

    # ─── F18 — Mercado dinâmico ───────────────────────────────────────────────

    def _recalc_prices(self) -> None:
        """Ajusta preços com base no estoque: escassez sobe preço, abundância baixa."""
        for item, base in MARKET_BASE_PRICES.items():
            stock = self.market_stock.get(item, 0)
            base_stock = MARKET_STOCK.get(item, 1)
            ratio = stock / max(base_stock, 1)
            # ratio < 1 → escassez → preço sobe; ratio > 1 → excesso → preço cai
            self.market_prices[item] = round(base * max(0.5, min(3.0, 1.0 / max(ratio, 0.1))), 2)

    def recalculate_market(self, reason: str = "manual") -> Dict[str, Any]:
        """Força recálculo dos preços e retorna snapshot atualizado do mercado."""
        self._recalc_prices()
        return {
            "reason": reason,
            "tick": self.world.ticks,
            "prices": dict(self.market_prices),
            "stock": dict(self.market_stock),
        }

    def market_buy(self, agent_id: str, item: str, qty: int, events: list) -> Dict:
        """Agente compra qty unidades de item do mercado central."""
        agent = next((a for a in self.world.agents if a.id == agent_id), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        if item not in self.market_prices:
            return {"error": f"Item '{item}' não disponível. Disponíveis: {list(self.market_prices)}"}
        if self.market_stock.get(item, 0) < qty:
            return {"error": f"Estoque insuficiente: {self.market_stock.get(item, 0)} disponíveis"}
        total_cost = self.market_prices[item] * qty
        if self.coins.get(agent_id, 0) < total_cost:
            return {"error": f"Moedas insuficientes ({self.coins.get(agent_id, 0):.1f} < {total_cost:.1f})"}

        # Executa
        self.coins[agent_id] = self.coins.get(agent_id, 0) - total_cost
        self.market_stock[item] = self.market_stock.get(item, 0) - qty
        for _ in range(qty):
            agent.inventory.append(item)
        self._recalc_prices()

        tx = {"type": "buy", "agent": agent.name, "agent_id": agent_id,
              "item": item, "qty": qty, "total": total_cost,
              "new_price": self.market_prices[item], "tick": self.world.ticks}
        self.market_tx_log.append(tx)
        events.append({
            "agent_id": agent_id, "name": agent.name,
            "action": "market_buy",
            "event_msg": f"🛒 {agent.name} comprou {qty}x {item} por {total_cost:.1f} moedas"
        })
        return tx

    def market_sell(self, agent_id: str, item: str, qty: int, events: list) -> Dict:
        """Agente vende qty unidades de item ao mercado central."""
        agent = next((a for a in self.world.agents if a.id == agent_id), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        owned = agent.inventory.count(item)
        if owned < qty:
            return {"error": f"{agent.name} tem apenas {owned}x {item}"}

        price_per = self.market_prices.get(item, 1.0)
        total_revenue = price_per * qty
        for _ in range(qty):
            agent.inventory.remove(item)
        self.coins[agent_id] = self.coins.get(agent_id, 0) + total_revenue
        self.market_stock[item] = self.market_stock.get(item, 0) + qty
        self._recalc_prices()

        tx = {"type": "sell", "agent": agent.name, "agent_id": agent_id,
              "item": item, "qty": qty, "total": total_revenue,
              "new_price": self.market_prices[item], "tick": self.world.ticks}
        self.market_tx_log.append(tx)
        events.append({
            "agent_id": agent_id, "name": agent.name,
            "action": "market_sell",
            "event_msg": f"💰 {agent.name} vendeu {qty}x {item} por {total_revenue:.1f} moedas"
        })
        return tx

    # ─── F19 — Contratos ──────────────────────────────────────────────────────

    def post_contract(self, requester_id: str, item: str, qty: int, reward: float) -> Dict:
        """Publica um contrato de entrega."""
        requester = next((a for a in self.world.agents if a.id == requester_id), None)
        if not requester:
            return {"error": "Agente não encontrado"}
        if self.coins.get(requester_id, 0) < reward:
            return {"error": "Moedas insuficientes para garantir a recompensa do contrato"}

        # Reserva a recompensa
        self.coins[requester_id] = self.coins.get(requester_id, 0) - reward
        self.contract_id_seq += 1
        contract = {
            "id": self.contract_id_seq,
            "requester_id": requester_id,
            "requester": requester.name,
            "item": item, "qty": qty, "reward": reward,
            "status": "open",
            "posted_tick": self.world.ticks,
            "fulfilled_by": None,
            "fulfilled_tick": None,
        }
        self.contracts.append(contract)
        logger.info(f"F19: Contract#{contract['id']} posted by {requester.name}: {qty}x {item} for {reward}")
        return contract

    def fulfill_contract(self, agent_id: str, contract_id: int, events: list) -> Dict:
        """Agente cumpre um contrato aberto e recebe a recompensa."""
        agent = next((a for a in self.world.agents if a.id == agent_id), None)
        if not agent:
            return {"error": "Agente não encontrado"}
        contract = next((c for c in self.contracts if c["id"] == contract_id), None)
        if not contract:
            return {"error": "Contrato não encontrado"}
        if contract["status"] != "open":
            return {"error": f"Contrato já {contract['status']}"}
        if contract["requester_id"] == agent_id:
            return {"error": "Você não pode cumprir seu próprio contrato"}

        owned = agent.inventory.count(contract["item"])
        if owned < contract["qty"]:
            return {"error": f"Você tem apenas {owned}x {contract['item']} (precisa {contract['qty']})"}

        # Executa
        for _ in range(contract["qty"]):
            agent.inventory.remove(contract["item"])
        requester = next((a for a in self.world.agents if a.id == contract["requester_id"]), None)
        if requester:
            for _ in range(contract["qty"]):
                requester.inventory.append(contract["item"])
        self.coins[agent_id] = self.coins.get(agent_id, 0) + contract["reward"]
        self.trade_reputation[agent_id] = self.trade_reputation.get(agent_id, 0) + 2.0
        contract["status"] = "fulfilled"
        contract["fulfilled_by"] = agent.name
        contract["fulfilled_tick"] = self.world.ticks

        events.append({
            "agent_id": agent_id, "name": agent.name,
            "action": "contract_fulfilled",
            "event_msg": f"📜 {agent.name} cumpriu contrato #{contract_id}! +{contract['reward']:.1f} moedas"
        })
        logger.info(f"F19: Contract#{contract_id} fulfilled by {agent.name}")
        return contract

    # ─── Tick ────────────────────────────────────────────────────────────────

    def tick(self, events: list) -> None:
        """Atualiza preços a cada 10 ticks."""
        if not self.active:
            return
        if self.world.ticks % 10 == 0:
            self._recalc_prices()

    # ─── Estado ──────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "market_prices": self.market_prices,
            "market_stock": self.market_stock,
            "contracts_open": [c for c in self.contracts if c["status"] == "open"],
            "contracts_total": len(self.contracts),
            "trade_log_count": len(self.market_tx_log),
            "craft_log_count": len(self.craft_log),
            "coins": self.coins,
            "trade_reputation": self.trade_reputation,
            "recipes": {k: v["description"] for k, v in RECIPES.items()},
        }
