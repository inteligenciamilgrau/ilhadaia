"""
T11 — Structured Output com Pydantic.

Define o schema ActionDecision que a IA deve retornar.
Usado pelo Thinker para validar e parsear as respostas de qualquer adapter.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional

# Ações válidas no world
VALID_ACTIONS = {
    # Base (survival)
    "move", "move_to", "attack", "speak", "wait",
    "eat", "drink", "gather", "fill_bottle", "pickup_body", "bury",
    # Warfare (F13-F16)
    "throw", "capture_zone",
    # Economy (F17-F19)
    "trade", "buy", "sell", "craft",
    # GangWar/Hybrid (F20)
    "sabotage", "supply",
}

# Intenções de alto nível para benchmark
VALID_INTENTS = {
    "survive", "attack", "befriend", "explore",
    "gather_resources", "heal", "help", "hide",
    # Mode-specific
    "conquer", "defend", "trade", "cooperate", "sabotage",
}


class ActionDecision(BaseModel):
    """Schema Pydantic da decisão de IA de um agente.
    
    O adapter deve retornar JSON compatível com este schema.
    O Thinker valida e usa os campos.
    """
    thought: str = Field(
        default="",
        max_length=500,
        description="Raciocínio interno do agente (não visto pelos outros)",
    )
    speak: str = Field(
        default="",
        max_length=200,
        description="Fala do agente (visível no chat)",
        alias="speak",
    )
    action: str = Field(
        default="wait",
        description=f"Ação a executar. Válidos: {', '.join(sorted(VALID_ACTIONS))}",
    )
    target_name: str = Field(
        default="",
        max_length=50,
        description="Nome do alvo da ação (agente ou item)",
    )
    intent: str = Field(
        default="survive",
        description=f"Intenção estratégica. Válidas: {', '.join(sorted(VALID_INTENTS))}",
    )
    params: dict = Field(
        default_factory=dict,
        description="Parâmetros extras da ação (ex: {dx: 1, dy: 0} para move)",
    )

    model_config = {"populate_by_name": True}

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_ACTIONS:
            return "wait"  # fallback seguro
        return v

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_INTENTS:
            return "survive"
        return v

    @field_validator("thought", "speak", "target_name", mode="before")
    @classmethod
    def coerce_to_str(cls, v) -> str:
        return str(v) if v is not None else ""

    def to_world_action(self, agent_id: str, agent_name: str) -> dict:
        """Converte para o formato de ação esperado pelo World._apply_action."""
        result = {
            "agent_id": agent_id,
            "name": agent_name,
            "thought": self.thought,
            "action": self.action,
            "speak": self.speak,
            "target_name": self.target_name,
        }
        result.update(self.params)
        return result

    def is_valid(self) -> bool:
        return self.action in VALID_ACTIONS

    @classmethod
    def from_dict(cls, data: dict) -> "ActionDecision":
        """Parse seguro de um dicionário (vindo da IA). Não lança exceção."""
        try:
            # Normaliza campo 'speech' para 'speak' (variação comum de LLMs)
            if "speech" in data and "speak" not in data:
                data["speak"] = data.pop("speech")
            return cls.model_validate(data)
        except Exception:
            return cls()  # fallback: wait

    @classmethod
    def get_json_schema_prompt(cls, game_mode: str = "survival") -> str:
        """Retorna instruções de schema para inserir no system prompt da IA."""
        base_actions = "move | move_to | attack | speak | wait | eat | drink | gather | fill_bottle | pickup_body | bury"
        mode_actions = ""
        if game_mode == "warfare":
            mode_actions = " | throw | capture_zone"
        elif game_mode == "economy":
            mode_actions = " | trade | buy | sell | craft"
        elif game_mode in ("gangwar", "hybrid"):
            mode_actions = " | throw | sabotage | supply | buy | sell"
        elif game_mode == "gincana":
            mode_actions = ""  # ações base servem (move_to checkpoints)

        all_actions = base_actions + mode_actions

        return f"""Retorne APENAS um objeto JSON válido com exatamente estes campos:
{{
  "thought": "seu raciocínio interno (string, max 500 chars)",
  "speak": "o que você diz em voz alta (string, pode ser vazio)",
  "action": "uma das ações: {all_actions}",
  "target_name": "nome do alvo se aplicável (string, pode ser vazio)",
  "intent": "sua intenção: survive | attack | befriend | explore | gather_resources | heal | help | hide | conquer | defend | trade | cooperate | sabotage",
  "params": {{}}
}}
NÃO inclua markdown, explicações ou texto fora do JSON."""
