# F16 - TERRITORY CONTROL

## Status de implementacao (2026-03-18)

- Backend: concluido
- Contratos de API: alinhados
- Frontend: integrado na aba Feature Ops (`frontend/models.html`)
- Referencia de fechamento: docs/features/IMPLEMENTATION_STATUS_2026-03-18.md


## Visao tecnica

Esta task define a implementacao de `F16` no modo `warfare/hybrid`.

Objetivo central:

- Disputa por zonas estrategicas

## Requisitos de mapa e escala

Mapa recomendado 40+ com 2-4 zonas de controle.

Regras obrigatorias:

- nao introduzir coordenadas hardcoded de mapa antigo (20x20)
- usar sempre `world.size` como base de validacao espacial
- validar spawn, pathing e colisao para `WORLD_SIZE` maior que 20

## Requisitos de objetos por modo

Objetos: `control_zone`, `zone_beacon`, `zone_supply`.

Padrao de implementacao:

- mapear objeto em factory de spawn por `game_mode`
- definir validacao de interacao por tipo de objeto
- garantir serializacao no state enviado via WebSocket

## Contratos de API previstos

- `POST /zones/config`
- `GET /zones/state`

Observacao:

- estes endpoints sao referencia de contrato de feature; podem ser ajustados desde que o contrato final fique documentado e versionado.

## Entregas backend

- criar/ajustar schema de entrada e saida da feature
- implementar regra principal no runtime (`world`, `thinker`, `agent` ou `storage`)
- persistir dados relevantes em SQLite/NDJSON quando aplicavel
- expor endpoint de leitura para observabilidade da feature
- registrar eventos no `decision_log` ou log de modo quando necessario

## Entregas frontend

- adicionar controles de uso da feature em tela apropriada (`index`, `dashboard` ou `models`)
- renderizar estado da feature em tempo real com fallback visual seguro
- incluir estados de erro, loading e ausencia de dados
- manter responsividade minima desktop/mobile

## Testes obrigatorios

- unitarios de regras centrais da feature
- integracao API com cenarios de sucesso e falha
- validacao de serializacao no payload de estado
- regressao para garantir que modo `survival` base nao quebrou

## Checklist tecnico de implementacao

- [ ] alinhar contrato da feature com `docs/FEATURE_PLAN.md`
- [ ] definir schemas pydantic de request/response
- [ ] implementar regras de dominio da feature
- [ ] adicionar persistencia e migration se necessaria
- [ ] expor endpoint(s) de operacao e leitura
- [ ] adicionar integracao no frontend
- [ ] validar compatibilidade com mapa ampliado
- [ ] cobrir com testes unitarios e integracao
- [ ] atualizar docs da propria feature com decisoes finais
- [ ] atualizar `docs/features/CHECKLIST.md`

## Criterios de aceite

- funcionalidade principal da feature operando no modo alvo
- dados da feature visiveis no frontend sem erro de render
- estado persistido corretamente quando aplicavel
- testes da feature executando com sucesso
- sem regressao funcional critica no loop principal da ilha

## Dependencias diretas

Dependencias: zonas de mapa + score por dominacao.

## Fora de escopo desta task

- otimizar multi-worker/cluster nesta fase
- reescrever arquitetura inteira de render
- unificar todos os modos em uma unica regra monolitica
