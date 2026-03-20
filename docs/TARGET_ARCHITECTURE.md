# Target Architecture - BBBia

Atualizado em: 2026-03-18

## Contexto

A base atual esta funcional e coberta por testes, mas o crescimento de features deixou `backend/main.py` com alto acoplamento. Este documento define a arquitetura alvo incremental sem reescrita total.

## Estado atual resumido

- API + orquestracao + parte de integracao concentradas em `backend/main.py`.
- `World` e engines em `backend/world.py` e `backend/runtime/*`.
- Persistencia em `backend/storage/*`.
- Frontend servido por `/frontend`.

## Objetivo da arquitetura alvo

Separar responsabilidades para facilitar:

- manutencao por dominio
- testes isolados
- evolucao para multi-worker
- onboarding tecnico

## Desenho alvo

```text
backend/
  api/
    app.py
    deps.py
    routes/
      world.py
      agents.py
      admin.py
      modes.py
      economy.py
      webhooks.py
      analytics.py
    ws/
      manager.py
      broadcaster.py
  services/
    world_service.py
    feature_service.py
    webhook_service.py
    benchmark_service.py
  simulation/
    world.py
    entities.py
    ticks.py
    serializers.py
  runtime/
    thinker.py
    profiles.py
    engines/
      gincana_engine.py
      warfare_engine.py
      economy_engine.py
      gangwar_engine.py
  storage/
    session_store.py
    decision_log.py
    replay_store.py
    memory_store.py
    webhook_manager.py
```

## Contratos a preservar

- Schemas e payloads dos endpoints em `docs/API_REFERENCE.md`.
- Semantica de `game_mode` no reset e nos aliases de feature.
- Formato de mensagens WebSocket (`init`, `update`, `reset`).

## Plano incremental de migracao

### Fase 1 - Extracao de rotas

- criar modulos de rotas por dominio
- manter `main.py` como orquestrador temporario

### Fase 2 - Servicos

- mover regras HTTP-orientadas para camada `services`
- reduzir logica inline nos handlers

### Fase 3 - WS desacoplado

- extrair broadcaster para componente proprio
- preparar interface para pub/sub externo

### Fase 4 - Escalabilidade

- introduzir barramento (ex.: Redis pub/sub)
- habilitar mais de um worker com consistencia de broadcast

## Riscos

- regressao de contratos se a extracao nao for guiada por testes.
- aumento de complexidade de deploy sem ganho imediato se a ordem de migracao for invertida.

## Criterios de sucesso

- `main.py` reduzido para bootstrap + wiring.
- contratos de API mantidos.
- suite de testes segue verde.
- pronto para escalar sem refatoracao estrutural adicional.
