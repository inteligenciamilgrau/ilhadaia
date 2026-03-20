# Frontend QA Checklist - 2026-03-18

Objetivo: validar em desktop e mobile os fluxos de UI conectados ao backend atualizado.

## Escopo de telas

- `frontend/index.html`
- `frontend/dashboard.html`
- `frontend/models.html`

## Preparacao

1. Subir backend em `http://localhost:8001`.
2. Confirmar sessao ativa com `GET /`.
3. Definir `ADMIN_TOKEN` para fluxos protegidos.
4. Abrir as tres telas no ambiente local.

## Roteiro rapido na UI oficial

1. Ir em `frontend/models.html`.
2. Abrir a aba `Feature Ops`.
3. Validar os blocos:
   - Bloco A: `F01..F09`
   - Bloco B: `F12..F16`
   - Bloco C: `F10/F11/F17..F20`
4. Confirmar retorno de cada acao em `Resultado Feature Ops`.
5. Em acoes admin, validar fluxo de prompt de token quando receber `401`.

## Matriz de execucao

- Desktop: Chrome/Chromium, viewport >= 1366x768
- Mobile 1: 390x844
- Mobile 2: 360x800

## Checklist funcional

### Core

- [ ] Carregamento inicial sem erro de console.
- [ ] WebSocket recebe `init` e `update` continuamente.
- [ ] Reset da sessao reflete na UI sem necessidade de refresh manual.

### F01/F03/F05

- [ ] Comando humano enviado e cancelado via UI.
- [ ] Decisoes/memoria carregam sem erro no inspector.
- [ ] Acoes admin de spawn/evento/perfil funcionam e refletem no estado.

### F04/F07/F08

- [ ] Eventos dinamicos visiveis sem quebra visual.
- [ ] Fluxos de alianca/traicao atualizam estado social exibido.
- [ ] Missoes aparecem e progridem de forma coerente.

### F12/F13/F14/F15/F16

- [ ] Gincana inicia e exibe estado/template sem erro.
- [ ] Warfare inicia e exibe estado/territorio/roles sem erro.
- [ ] Acao de throw e feedback de combate funcionam.

### F10/F17/F18/F19/F20

- [ ] Fluxos de economia (recipes/craft/build) executam sem quebra de tela.
- [ ] Mercado (prices/buy/sell) sincroniza com dados de backend.
- [ ] Contratos podem ser criados e cumpridos sem desincronizacao.
- [ ] Gangwar/hybrid atualizam componentes e estado visual.

### F11

- [ ] Fluxo de cadastro/listagem/remocao de webhook na UI (quando presente) sem erro.
- [ ] Fluxos de teste/stats/history nao causam falhas no frontend.

## Responsividade minima

- [ ] Controles essenciais acessiveis no mobile.
- [ ] Sem overflow horizontal critico.
- [ ] Modais e interacoes funcionam por mouse e toque.

## Evidencias obrigatorias

Para cada item marcado como concluido:

- registrar data e hora
- registrar viewport/ambiente
- anexar screenshot ou observacao objetiva
- abrir bug com reproducao quando houver falha
