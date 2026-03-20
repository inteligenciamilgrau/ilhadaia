# Checklist de Implementacao - BBBia

Atualizado em: 2026-03-18

Legenda:

- `[ ]` nao iniciado
- `[-]` em andamento
- `[x]` concluido

## Fundacao

- [x] P00 - mundo ampliado com mapa padrao 32x32 validado em backend e frontend
- [x] P00 - matriz de objetos por modo implementada no spawn
- [x] P00 - configuracao `game_mode` persistida por sessao

## Fase 1

- [x] F01 - Modo Comandante
- [x] F03 - Decision Inspector
- [x] F05 - Console de Intervencao

## Fase 2

- [x] F02 - Comparador A/B
- [x] F06 - Temporadas e ELO
- [x] F09 - Versionamento de Perfis

## Fase 3

- [x] F04 - Eventos Dinamicos
- [x] F08 - Missoes Individuais
- [x] F07 - Reputacao Social

## Fase 4

- [x] F12 - Modo Gincana

## Fase 5

- [x] F13 - Guerra de Faccoes
- [x] F14 - Combate de Arremesso
- [x] F15 - Papeis Taticos
- [x] F16 - Controle de Territorio

## Fase 6

- [x] F17 - Modo Economia Local
- [x] F10 - Economia e Crafting
- [x] F18 - Mercado Dinamico
- [x] F19 - Contratos e Reputacao Comercial

## Fase 7

- [x] F20 - Guerra de Gangues

## Fase 8

- [x] F11 - Webhooks Expandidos

## Evidencias tecnicas da rodada

- [x] testes backend executados: `200 passed, 1 skipped`
- [x] contratos docs x rotas backend validados
- [x] referencia global de API atualizada

## Checkpoints finais para 100%

- [x] completar integracao de UI para contratos das features (cobertura funcional F01..F20: `48/48`)
- [ ] validar impacto no frontend em desktop e mobile (checklist QA com evidencia)
- [-] atualizar dashboard/observabilidade quando aplicavel (em andamento)
- [x] consolidar status tecnico em `IMPLEMENTATION_STATUS_2026-03-18.md`
