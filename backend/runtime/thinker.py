"""
Thinker — orquestrador central de decisões de IA.
Verifica elegibilidade (cooldown/budget), monta contexto, chama o adapter
correto, valida via ActionDecision (T11) e registra no DecisionLog.
Integrado com AgentMemory 4 camadas (T10).
"""
import json
import logging
from typing import Optional

from .adapters.base import AIAdapter, AIResponse
from .adapters.openai_compatible import OpenAICompatibleAdapter
from .profiles import AgentProfile, get_profile
from .relevance import get_relevant_summary
from .schemas import ActionDecision
from storage.decision_log import DecisionLog, DecisionRecord

logger = logging.getLogger("BBB_IA.Thinker")


class Thinker:
    """Ponto central que orquestra chamadas de IA para qualquer agente."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log
        self._adapters: dict[str, AIAdapter] = {}

    # ── Adapter cache ───────────────────────────────────────────────────────

    def get_adapter(self, profile: AgentProfile) -> AIAdapter:
        """Retorna (ou cria) o adapter OpenAI-compatible para o perfil dado."""
        key = profile.profile_id
        if key not in self._adapters:
            self._adapters[key] = OpenAICompatibleAdapter(
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
        return self._adapters[key]

    # ── Main think ──────────────────────────────────────────────────────────

    async def think(
        self,
        agent,
        world_context: dict,
        current_tick: int,
        session_id: str,
    ) -> Optional[dict]:
        """
        Tenta fazer o agente pensar. Retorna dict de ação ou None se skipped.
        1. Verifica cooldown e budget
        2. Chama adapter → raw AIResponse
        3. Valida via ActionDecision (T11)
        4. Atualiza memória 4 camadas (T10)
        5. Loga no DecisionLog
        """
        # 1. Verificar elegibilidade
        if not agent.can_think(current_tick):
            reason = (
                "skip_cooldown"
                if current_tick - agent.last_thought_tick < agent.cooldown_ticks
                else "skip_budget"
            )
            logger.debug(f"[{agent.name}] skip: {reason}")
            self.log.log_skip(
                session_id=session_id,
                tick=current_tick,
                agent_id=agent.id,
                agent_name=agent.name,
                reason=reason,
            )
            return None

        # 2. Buscar perfil e adapter
        profile = get_profile(getattr(agent, "profile_id", "claude-kiro"))
        adapter = self.get_adapter(profile)

        # 3. Montar prompts
        game_mode = getattr(agent, '_game_mode', 'survival')
        system_prompt = self._build_system_prompt(agent, game_mode)
        user_context = self._build_user_context(agent, world_context, current_tick, game_mode)

        # 4. Chamar IA
        try:
            response: AIResponse = await adapter.think(
                system_prompt=system_prompt,
                user_context=user_context,
                max_tokens=profile.max_tokens,
                temperature=profile.temperature,
            )
        except Exception as e:
            logger.error(f"[{agent.name}] adapter error: {e}")
            self.log.log(DecisionRecord(
                session_id=session_id, tick=current_tick,
                agent_id=agent.id, agent_name=agent.name,
                model=profile.model, provider=profile.provider,
                latency_ms=0.0, prompt_tokens=0, completion_tokens=0,
                thought="", speech="", action="wait", action_params={},
                result="error",
            ))
            return None

        # 5. Validar via ActionDecision (T11)
        raw_dict = {
            "thought": response.thought,
            "speak": response.speech,
            "action": response.action,
            "target_name": response.target_name,
            "intent": response.intent,
            "params": response.action_params,
        }
        decision = ActionDecision.from_dict(raw_dict)
        is_invalid = response.action != decision.action  # action foi corrigida para wait?

        # 6. Atualizar estado do agente
        tokens_delta = response.total_tokens
        agent.tokens_used += tokens_delta
        agent.last_thought_tick = current_tick
        agent.benchmark["decisions_made"] += 1
        
        # Cálculo de custo (estimado $0.002 / 1k tokens)
        cost_delta = (tokens_delta / 1000.0) * 0.002
        agent.benchmark["cost_usd"] = agent.benchmark.get("cost_usd", 0.0) + cost_delta
        
        # Cálculo de score (decisão válida = 1.0, tokens dão mini-bonus de atividade)
        score_delta = 1.0 if not is_invalid else 0.1
        agent.benchmark["score"] = agent.benchmark.get("score", 0.0) + score_delta

        if is_invalid:
            agent.benchmark["invalid_actions"] += 1

        logger.info(f"[{agent.name}] AI logic: tokens={tokens_delta}, cost=${cost_delta:.5f}, score_delta={score_delta}")

        # 7. Atualizar memória 4 camadas (T10)
        agent_memory = getattr(agent, "agent_memory", None)
        if agent_memory is not None:
            agent_memory.add_short_term(
                tick=current_tick,
                action=decision.action,
                thought=decision.thought[:100],
                result="ok" if not is_invalid else "action_corrected",
            )
            # Evento episódico para ações críticas
            if decision.action in ("attack", "bury", "pickup_body"):
                agent_memory.add_episodic(
                    tick=current_tick,
                    event_type=decision.action,
                    description=f"{agent.name} executou {decision.action} em {decision.target_name or 'alvo'}",
                    agents_involved=[decision.target_name] if decision.target_name else [],
                )

        # 8. Logar decisão
        self.log.log(DecisionRecord(
            session_id=session_id,
            tick=current_tick,
            agent_id=agent.id,
            agent_name=agent.name,
            model=profile.model,
            provider=profile.provider,
            latency_ms=response.latency_ms,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            thought=decision.thought,
            speech=decision.speak,
            action=decision.action,
            action_params=decision.params,
            result="invalid" if is_invalid else "success",
        ))

        # 9. Formatar retorno compatível com o World
        return decision.to_world_action(agent.id, agent.name)

    # ── Prompt builders ─────────────────────────────────────────────────────

    # ── Descrições por modo ──────────────────────────────────────────────────
    MODE_DESCRIPTIONS = {
        "survival": (
            "sobrevivência na ilha. Encontre comida (colha frutas das árvores), "
            "beba água (vá até o lago), mantenha sua saúde e sobreviva à noite. "
            "Se alguém morrer, leve o corpo ao cemitério."
        ),
        "warfare": (
            "GUERRA DE FACÇÕES (Alpha vs Beta). VOCÊ DEVE LUTAR! "
            "Ataque inimigos da facção oposta com 'attack'. "
            "Pegue pedras arremessáveis ('throwable_stone') e use a ação 'throw' para causar dano AOE. "
            "Vá até a Zona Central e use 'capture_zone' para capturá-la (3 ticks seguidos). "
            "Defenda sua base. O objetivo é ter mais pontos que a facção inimiga. "
            "PRIORIZE combate e captura de zona acima de sobrevivência!"
        ),
        "gincana": (
            "GINCANA COOPERATIVA em equipe! "
            "Trabalhe com os outros agentes para visitar TODOS os 4 checkpoints usando 'move_to'. "
            "Depois, encontre o Artefato Principal e leve-o até a Zona de Entrega. "
            "Conversem, coordenem quem vai para qual checkpoint! "
            "PRIORIZE cooperação e velocidade sobre sobrevivência."
        ),
        "economy": (
            "ECONOMIA e COMÉRCIO. Seu objetivo é ganhar dinheiro! "
            "Vá até os Mercados e use 'buy' ou 'sell' para negociar items. "
            "Complete contratos entregando os itens pedidos para ganhar moedas. "
            "Use 'craft' para fabricar itens valiosos (precisa de materiais no inventário). "
            "Use 'trade' para propor trocas diretas com outros agentes. "
            "PRIORIZE lucro e negociação sobre sobrevivência!"
        ),
        "gangwar": (
            "GUERRA DE GANGUES! Modo híbrido de guerra + economia clandestina. "
            "Use o Mercado Negro para comprar itens especiais ('buy'). "
            "Use 'sabotage' nos depósitos da facção inimiga para destruir seus recursos. "
            "Capture supply posts com 'supply' para gerar renda passiva. "
            "Ataque inimigos, defenda seus recursos! PRIORIZE combate e sabotagem!"
        ),
        "hybrid": (
            "MODO HÍBRIDO: guerra de gangues + economia. "
            "Combine estratégias de combate E economia. "
            "Use o Mercado Negro, sabote o inimigo, capture supply posts, "
            "e tente dominar tanto militarmente quanto economicamente!"
        ),
    }

    MODE_TIPS = {
        "warfare": [
            "Se há um inimigo perto, ATAQUE com 'attack' ou 'throw'.",
            "Se ninguém está na Zona Central, vá capturá-la com 'capture_zone'.",
            "'throw' causa dano em área (raio 1) — eficaz contra grupos.",
            "Scouts se movem mais rápido, Medics curam aliados, Warriors causam mais dano.",
        ],
        "gincana": [
            "Comunique-se: diga aos outros qual checkpoint você vai pegar.",
            "Divida os checkpoints: cada agente pega um diferente.",
            "Quando todos os checkpoints estiverem capturados, vá buscar o artefato.",
        ],
        "economy": [
            "Colha frutas e venda no Mercado por moedas.",
            "Verifique os contratos disponíveis — eles dão boas recompensas.",
            "Negocie com outros agentes: 'trade target_name=João' para propor troca.",
        ],
        "gangwar": [
            "O Mercado Negro vende itens poderosos mas caros.",
            "Sabote depósitos inimigos para enfraquecer a facção adversária.",
            "Supply posts geram renda passiva — capture-os!",
        ],
    }

    def _build_system_prompt(self, agent, game_mode: str = "survival") -> str:
        """Constrói o system prompt variando por modo de jogo."""
        base_instruction = getattr(agent, "system_instruction", None)
        if base_instruction:
            return base_instruction

        mode_desc = self.MODE_DESCRIPTIONS.get(game_mode, self.MODE_DESCRIPTIONS["survival"])
        tips = self.MODE_TIPS.get(game_mode, [])
        tips_text = ""
        if tips:
            tips_text = "\n\nDICAS IMPORTANTES:\n" + "\n".join(f"• {t}" for t in tips)

        from .schemas import ActionDecision
        return f"""Você é {agent.name}, um personagem em uma simulação de {mode_desc}
Sua personalidade: {agent.personality}
{tips_text}

{ActionDecision.get_json_schema_prompt(game_mode)}"""

    def _build_user_context(self, agent, world_context: dict, tick: int, game_mode: str = "survival") -> str:
        """Constrói o contexto do usuário integrando memória + estado do modo."""
        # Pega o contexto de memória se disponível
        memory_ctx = ""
        agent_memory = getattr(agent, "agent_memory", None)
        if agent_memory is not None:
            relevance_query = " ".join([
                str(world_context.get("reachable_now", "")),
                str(world_context.get("visible_entities", ""))[:400],
                f"hp={agent.hp} hunger={agent.hunger} thirst={agent.thirst}",
            ])
            relevant_episodes = get_relevant_summary(
                agent_memory.episodic,
                context=relevance_query,
                current_tick=tick,
                top_k=5,
            )
            memory_ctx = (
                f"\n{agent_memory.to_prompt_context()}\n\n"
                f"🎯 EPISÓDIOS MAIS RELEVANTES AGORA:\n{relevant_episodes}\n"
            )

        # ── Contexto específico do modo ──
        mode_ctx = ""
        if game_mode == "warfare":
            wf = world_context.get("warfare_info", {})
            if wf:
                mode_ctx = f"""
🎖️ MODO WARFARE — INFORMAÇÕES DE COMBATE:
SUA FACÇÃO: {wf.get('faction', '?').upper()}
SEU PAPEL: {wf.get('role', '?')} (scout=rápido, medic=cura, warrior=forte)
PONTUAÇÃO: Alpha={wf.get('alpha_score', 0):.0f} vs Beta={wf.get('beta_score', 0):.0f}
BASES HP: Alpha={wf.get('alpha_base_hp', 100):.0f} | Beta={wf.get('beta_base_hp', 100):.0f}
ZONA CENTRAL: controlada por {wf.get('territory_holder') or 'NINGUÉM'} (capture_ticks={wf.get('territory_ticks', 0)})
ARREMESSOS FEITOS: {wf.get('throws', 0)}
"""
        elif game_mode == "gincana":
            gin = world_context.get("gincana_info", {})
            if gin:
                cps = gin.get('checkpoints_status', 'desconhecido')
                mode_ctx = f"""
🏁 MODO GINCANA — INFORMAÇÕES DA CORRIDA:
CHECKPOINTS CAPTURADOS: {cps}
ARTEFATO COLETADO: {'SIM' if gin.get('artifact_collected') else 'NÃO — vá buscá-lo!'}
ENTREGA FEITA: {'SIM ✓' if gin.get('delivery_done') else 'NÃO — leve o artefato à Zona de Entrega!'}
TICKS RESTANTES: {gin.get('remaining_ticks', '?')}
"""
        elif game_mode == "economy":
            eco = world_context.get("economy_info", {})
            if eco:
                mode_ctx = f"""
💰 MODO ECONOMIA — INFORMAÇÕES COMERCIAIS:
SEU SALDO: {eco.get('balance', 0)} moedas
RECEITAS DISPONÍVEIS: {eco.get('recipes', 'axe, raft, wall, torch, bandage')}
MERCADO: {eco.get('market_summary', 'verifique no Mercado Central')}
CONTRATOS ATIVOS: {eco.get('contracts_count', 0)}
"""
        elif game_mode in ("gangwar", "hybrid"):
            gw = world_context.get("gangwar_info", {})
            if gw:
                mode_ctx = f"""
💣 MODO GUERRA DE GANGUES — INFORMAÇÕES:
SUA FACÇÃO: {gw.get('faction', '?').upper()}
SCORE: {gw.get('faction_scores', 'desconhecido')}
DEPÓSITOS: Alpha HP={gw.get('depot_alpha_hp', '?')} | Beta HP={gw.get('depot_beta_hp', '?')}
MERCADO NEGRO: Disponível (use 'buy' perto dele)
"""

        base = f"""
TICK ATUAL: {tick}
PERÍODO: {"🌙 NOITE" if world_context.get('is_night') else "☀️ DIA"}
MODO DE JOGO: {game_mode.upper()}
{mode_ctx}
SEU STATUS:
Posição: x={agent.x}, y={agent.y}
ZUMBI: {"SIM!" if getattr(agent, 'is_zombie', False) else "NÃO"}
Fome: {agent.hunger}/100 | Sede: {agent.thirst}/100 | HP: {agent.hp}/100
Bolsa: {world_context.get('inventory', [])}
Carregando corpo: {"SIM" if world_context.get('is_carrying_body') else "NÃO"}
{memory_ctx}
VOCÊ PODE INTERAGIR COM (ALCANCE IMEDIATO):
{json.dumps(world_context.get('reachable_now', []), indent=2, ensure_ascii=False)}

VOCÊ ESTÁ VENDO:
{json.dumps(world_context.get('visible_entities', []), indent=2, ensure_ascii=False)}

📊 BENCHMARK: tokens={agent.tokens_used}/{agent.token_budget} | decisões={agent.benchmark.get('decisions_made', 0)} | score={agent.benchmark.get('score', 0.0):.1f}

Qual é sua próxima ação? Retorne APENAS o JSON.
"""
        return base
