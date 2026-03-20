// ══════════════════════════════════════════════════════
//  BBBia Admin Panel — admin.js
//  Cobre todas as features F01-F20 do backend
// ══════════════════════════════════════════════════════

const BASE = 'http://localhost:8001';

// ── Token ─────────────────────────────────────────────
function getToken() {
  const el = document.getElementById('token-input');
  return (el && el.value) || localStorage.getItem('bbia_admin_token') || '';
}
function saveToken() {
  const val = document.getElementById('token-input').value.trim();
  if (val) {
    localStorage.setItem('bbia_admin_token', val);
    toast('✓ Token salvo!', 'ok');
    highlightToken(false);
  }
}
function highlightToken(on) {
  const el = document.getElementById('token-input');
  if (!el) return;
  el.style.borderColor = on ? '#ff5370' : '';
  el.style.boxShadow = on ? '0 0 0 2px rgba(255,83,112,.4)' : '';
}
function requireToken() {
  const t = getToken();
  if (!t) {
    toast('⚠️ Insira o Admin Token no campo acima!', 'err');
    highlightToken(true);
    document.getElementById('token-input').focus();
    return false;
  }
  return true;
}
function adminHeaders() {
  return { 'Content-Type': 'application/json', 'X-Admin-Token': getToken() };
}
function publicHeaders() {
  return { 'Content-Type': 'application/json' };
}

// ── Tab switching ──────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  event.currentTarget.classList.add('active');
}

// ── Toast ──────────────────────────────────────────────
function toast(msg, type = 'ok') {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

// ── Generic fetch helpers ──────────────────────────────
async function api(method, path, body, headers) {
  const opts = { method, headers: headers || adminHeaders() };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  const data = await r.json().catch(() => ({ error: 'parse error' }));
  if (!r.ok) throw data;
  return data;
}
async function apiGet(path) { return api('GET', path, null, publicHeaders()); }
async function apiPost(path, body) { return api('POST', path, body); }
async function apiDelete(path) { return api('DELETE', path); }
// POST público (não requer admin token)
async function apiPostPublic(path, body) { return api('POST', path, body, publicHeaders()); }

function showOut(id, data, isErr) {
  const el = document.getElementById(id);
  el.style.display = 'block';
  el.className = 'output' + (isErr ? ' err' : '');
  el.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}

async function callAndShow(outId, method, path, body) {
  try {
    const res = method === 'GET' ? await apiGet(path) : await apiPost(path, body);
    showOut(outId, res);
    toast('✓ OK');
    return res;
  } catch (e) {
    showOut(outId, e, true);
    toast('Erro: ' + (e.detail || JSON.stringify(e)), 'err');
  }
}

// ══════════════════════════════════════════════════════
//  MUNDO
// ══════════════════════════════════════════════════════
async function loadServerStatus() {
  try {
    const [root, sys] = await Promise.all([apiGet('/'), apiGet('/system/info')]);
    showOut('server-status-out', { server: root, system: sys });
    document.getElementById('ws-dot').className = 'ok';
  } catch (e) {
    showOut('server-status-out', e, true);
    document.getElementById('ws-dot').className = '';
  }
}

async function resetWorld() {
  if (!requireToken()) return;
  const mode = document.getElementById('reset-mode').value;
  const pc = parseInt(document.getElementById('reset-players').value) || 4;
  if (!confirm(`Resetar mundo para modo "${mode}" com ${pc} agentes?`)) return;
  try {
    const res = await api('POST', '/reset', { game_mode: mode, player_count: pc });
    showOut('reset-out', res);
    document.getElementById('reset-out').style.display = 'block';
    toast('\u2713 Reset OK \u2014 modo: ' + mode);
    pollModeBadge();
  } catch (e) {
    showOut('reset-out', e, true);
    toast('Erro no reset: ' + (e.detail || JSON.stringify(e)), 'err');
  }
}

async function patchWorld() {
  if (!requireToken()) return;
  const body = {};
  const started = document.getElementById('patch-started').value;
  const interval = document.getElementById('patch-ai-interval').value;
  const chance = document.getElementById('patch-event-chance').value;
  const gameover = document.getElementById('patch-game-over').value;
  if (started !== '') body.started = started === 'true';
  if (interval !== '') body.ai_interval = parseInt(interval);
  if (chance !== '') body.event_chance = parseFloat(chance);
  if (gameover !== '') body.game_over = gameover === 'true';
  await callAndShow('patch-out', 'POST', '/admin/world/patch', body);
  document.getElementById('patch-out').style.display = 'block';
}

async function loadWorldState() {
  await callAndShow('patch-out', 'GET', '/admin/world/state');
  document.getElementById('patch-out').style.display = 'block';
}

async function spawnObject() {
  const body = { type: document.getElementById('spawn-type').value,
    quantity: parseInt(document.getElementById('spawn-qty').value) || 1 };
  const x = document.getElementById('spawn-x').value;
  const y = document.getElementById('spawn-y').value;
  if (x) body.x = parseInt(x);
  if (y) body.y = parseInt(y);
  await callAndShow('spawn-out', 'POST', '/admin/spawn', body);
  document.getElementById('spawn-out').style.display = 'block';
}

async function triggerAdminEvent() {
  const body = { event_type: document.getElementById('admin-event-type').value };
  const msg = document.getElementById('admin-event-msg').value;
  if (msg) body.message = msg;
  await callAndShow('admin-event-out', 'POST', '/admin/event', body);
  document.getElementById('admin-event-out').style.display = 'block';
}

async function loadSessions() {
  await callAndShow('sessions-out', 'GET', '/sessions');
}

console.log('✅ admin.js CARREGADO — Versão: POST/reset Headers v3');
// ══════════════════════════════════════════════════════
//  STATE & INITIALIZATIONES
// ══════════════════════════════════════════════════════
async function loadAgents() {
  try {
    const data = await apiGet('/agents/all');
    const agents = data.agents || data || [];
    const tbody = document.getElementById('agents-tbody');
    tbody.innerHTML = agents.map(a => `
      <tr>
        <td><strong>${a.name || a.id}</strong></td>
        <td>${a.hp ?? a.health ?? '?'}</td>
        <td><span class="badge badge-purple">${a.profile_id || '?'}</span></td>
        <td><span class="badge badge-blue">${a.faction || a.game_mode || '—'}</span></td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="prefillAgent('${a.id}')">Selec.</button>
          <button class="btn btn-danger btn-sm" onclick="deleteAgent('${a.id}')">🗑</button>
        </td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted)">Nenhum agente</td></tr>';
    toast('✓ ' + agents.length + ' agentes carregados');
  } catch (e) { toast('Erro ao carregar agentes: ' + (e.detail || e), 'err'); }
}

function prefillAgent(id) {
  ['cmd-agent-id','insp-agent-id','ally-agent-id','profile-agent-id'].forEach(el => {
    const f = document.getElementById(el);
    if (f) f.value = id;
  });
}

async function deleteAgent(id) {
  if (!confirm('Deletar agente ' + id + '?')) return;
  try {
    const r = await fetch(BASE + '/agent/' + id, { method: 'DELETE', headers: adminHeaders() });
    const d = await r.json();
    toast(r.ok ? '✓ Agente deletado' : 'Erro: ' + JSON.stringify(d), r.ok ? 'ok' : 'err');
    loadAgents();
  } catch (e) { toast('Erro: ' + e, 'err'); }
}

async function registerAgent() {
  const body = { name: document.getElementById('reg-name').value,
    profile_id: document.getElementById('reg-profile').value };
  await callAndShow('reg-out', 'POST', '/agents/register', body);
  document.getElementById('reg-out').style.display = 'block';
  loadAgents();
}

// F01 — Modo Comandante
async function sendCommand() {
  const id = document.getElementById('cmd-agent-id').value;
  if (!id) { toast('Informe o agent_id', 'err'); return; }
  await callAndShow('cmd-out', 'POST', `/agents/${id}/command`, {
    command: document.getElementById('cmd-text').value,
    ttl_ticks: parseInt(document.getElementById('cmd-ttl').value) || 5
  });
  document.getElementById('cmd-out').style.display = 'block';
}
async function cancelCommand() {
  const id = document.getElementById('cmd-agent-id').value;
  await callAndShow('cmd-out', 'POST', `/agents/${id}/command/cancel`, {});
  document.getElementById('cmd-out').style.display = 'block';
}
async function getCommand() {
  const id = document.getElementById('cmd-agent-id').value;
  await callAndShow('cmd-out', 'GET', `/agents/${id}/command`);
  document.getElementById('cmd-out').style.display = 'block';
}

// F03 — Decision Inspector
async function loadDecisions() {
  const id = document.getElementById('insp-agent-id').value;
  if (!id) { toast('Informe o agent_id', 'err'); return; }
  await callAndShow('insp-out', 'GET', `/agents/${id}/decisions`);
  document.getElementById('insp-out').style.display = 'block';
}
async function loadMemory() {
  const id = document.getElementById('insp-agent-id').value;
  await callAndShow('insp-out', 'GET', `/agents/${id}/memory/relevant`);
  document.getElementById('insp-out').style.display = 'block';
}
async function loadWallet() {
  const id = document.getElementById('insp-agent-id').value;
  await callAndShow('insp-out', 'GET', `/agents/${id}/wallet`);
  document.getElementById('insp-out').style.display = 'block';
}

// F07 — Aliança
async function formAlliance() {
  const id = document.getElementById('ally-agent-id').value;
  await callAndShow('ally-out', 'POST', `/agents/${id}/alliances`, { ally_name: document.getElementById('ally-name').value });
  document.getElementById('ally-out').style.display = 'block';
}
async function breakAlliance() {
  const id = document.getElementById('ally-agent-id').value;
  await callAndShow('ally-out', 'DELETE', `/agents/${id}/alliance`);
  document.getElementById('ally-out').style.display = 'block';
}
async function betrayAlliance() {
  const id = document.getElementById('ally-agent-id').value;
  await callAndShow('ally-out', 'POST', `/agents/${id}/betray`, {});
  document.getElementById('ally-out').style.display = 'block';
}
async function loadReputation() {
  const id = document.getElementById('ally-agent-id').value;
  await callAndShow('ally-out', 'GET', `/agents/${id}/reputation`);
  document.getElementById('ally-out').style.display = 'block';
}
async function changeProfile() {
  const id = document.getElementById('profile-agent-id').value;
  await callAndShow('profile-out', 'POST', `/admin/agent/${id}/profile`, {
    profile_id: document.getElementById('profile-new-profile').value });
  document.getElementById('profile-out').style.display = 'block';
}

// ══════════════════════════════════════════════════════
//  MODOS
// ══════════════════════════════════════════════════════
let selectedMode = 'survival';
function selectMode(card) {
  document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  selectedMode = card.dataset.mode;
}
async function applyModeReset() {
  if (!requireToken()) return;
  const pc = parseInt(document.getElementById('mode-players').value) || 4;
  if (!confirm(`Reset para modo "${selectedMode}" com ${pc} agentes?`)) return;
  try {
    const res = await api('POST', '/reset', { game_mode: selectedMode, player_count: pc });
    showOut('mode-out', res);
    document.getElementById('mode-out').style.display = 'block';
    toast('\u2713 Modo alterado para: ' + selectedMode);
    pollModeBadge();
  } catch (e) {
    showOut('mode-out', e, true);
    toast('Erro: ' + (e.detail || JSON.stringify(e)), 'err');
  }
}
// ── Quick Reset (usado pelos banners de pré-requisito) ──
async function quickReset(mode) {
  if (!requireToken()) return;
  const pc = parseInt(document.getElementById('mode-players')?.value) || 4;
  if (!confirm(`Quick Reset para "${mode}" com ${pc} agentes?`)) return;
  try {
    const res = await api('POST', '/reset', { game_mode: mode, player_count: pc });
    showOut('mode-out', res);
    toast('\u2713 Modo alterado para: ' + mode);
    pollModeBadge();
  } catch (e) {
    toast('Erro no quick reset: ' + (e.detail || JSON.stringify(e)), 'err');
  }
}
async function loadGincanaTemplates() {
  await callAndShow('gincana-templates-out', 'GET', '/gincana/templates');
}
async function loadCurrentModeState() {
  try {
    const mode = document.getElementById('mode-badge').textContent;
    let endpoint = '/state';
    if (mode === 'gincana') endpoint = '/gincana/state';
    else if (mode === 'warfare') endpoint = '/warfare/state';
    else if (mode === 'economy') endpoint = '/economy/state';
    else if (mode === 'gangwar' || mode === 'hybrid') endpoint = '/gangwar/state';
    await callAndShow('world-mode-state-out', 'GET', endpoint);
  } catch (e) { toast('Erro' + e, 'err'); }
}

// ══════════════════════════════════════════════════════
//  WARFARE
// ══════════════════════════════════════════════════════
async function startWarfare() { await callAndShow('warfare-state-out', 'POST', '/modes/warfare/start', {}); document.getElementById('warfare-state-out').style.display='block'; }
async function stopWarfare() { await callAndShow('warfare-state-out', 'POST', '/warfare/stop', {}); document.getElementById('warfare-state-out').style.display='block'; }
async function loadWarfareState() { await callAndShow('warfare-state-out', 'GET', '/warfare/state'); document.getElementById('warfare-state-out').style.display='block'; }
async function startGincana() {
  await callAndShow('gincana-state-out', 'POST', '/modes/gincana/start', { max_ticks: parseInt(document.getElementById('gincana-max-ticks').value) || 400 });
  document.getElementById('gincana-state-out').style.display='block';
}
async function stopGincana() { await callAndShow('gincana-state-out', 'POST', '/gincana/stop', {}); document.getElementById('gincana-state-out').style.display='block'; }
async function loadGincanaState() { await callAndShow('gincana-state-out', 'GET', '/gincana/state'); document.getElementById('gincana-state-out').style.display='block'; }

async function throwStone() {
  await callAndShow('throw-out', 'POST', '/actions/throw', {
    agent_id: document.getElementById('throw-agent').value,
    target_x: parseInt(document.getElementById('throw-x').value),
    target_y: parseInt(document.getElementById('throw-y').value)
  });
  document.getElementById('throw-out').style.display='block';
}
async function loadCombatConfig() { await callAndShow('throw-out', 'GET', '/combat/config'); document.getElementById('throw-out').style.display='block'; }

async function setTeamRoles() {
  const team = document.getElementById('team-id').value;
  let roles = {};
  const raw = document.getElementById('team-roles-json').value.trim();
  if (raw) { try { roles = JSON.parse(raw); } catch { toast('JSON inválido', 'err'); return; } }
  await callAndShow('roles-out', 'POST', `/teams/${team}/roles`, { roles });
  document.getElementById('roles-out').style.display='block';
}
async function getTeamRoles() {
  const team = document.getElementById('team-id').value;
  await callAndShow('roles-out', 'GET', `/teams/${team}/roles`);
  document.getElementById('roles-out').style.display='block';
}

async function loadTerritory() { await callAndShow('territory-out', 'GET', '/zones/state'); document.getElementById('territory-out').style.display='block'; }
async function configZone() {
  await callAndShow('territory-out', 'POST', '/zones/config', {
    name: document.getElementById('zone-name').value,
    x: parseInt(document.getElementById('zone-x').value),
    y: parseInt(document.getElementById('zone-y').value)
  });
  document.getElementById('territory-out').style.display='block';
}
async function loadWarfareFull() { await callAndShow('warfare-full-out', 'GET', '/warfare/state'); }

// ══════════════════════════════════════════════════════
//  ECONOMIA
// ══════════════════════════════════════════════════════
async function startEconomy() { await callAndShow('econ-out', 'POST', '/modes/economy/start', {}); document.getElementById('econ-out').style.display='block'; }
async function loadEconomyState() { await callAndShow('econ-out', 'GET', '/economy/state'); document.getElementById('econ-out').style.display='block'; }
async function loadCoins() { await callAndShow('econ-out', 'GET', '/economy/coins'); document.getElementById('econ-out').style.display='block'; }
async function loadRecipes() { await callAndShow('econ-out', 'GET', '/recipes'); document.getElementById('econ-out').style.display='block'; }

async function craftItem() {
  await callAndShow('craft-out', 'POST', '/craft', {
    agent_id: document.getElementById('craft-agent').value,
    recipe: document.getElementById('craft-recipe').value
  });
  document.getElementById('craft-out').style.display='block';
}

async function buildStructure() {
  await callAndShow('build-out', 'POST', '/build', {
    agent_id: document.getElementById('build-agent').value,
    structure_type: document.getElementById('build-type').value,
    x: parseInt(document.getElementById('build-x').value),
    y: parseInt(document.getElementById('build-y').value)
  });
  document.getElementById('build-out').style.display='block';
}

async function tradeItems() {
  await callAndShow('trade-out', 'POST', '/economy/trade', {
    seller_id: document.getElementById('trade-seller').value,
    buyer_id: document.getElementById('trade-buyer').value,
    item: document.getElementById('trade-item').value,
    price: parseInt(document.getElementById('trade-price').value)
  });
  document.getElementById('trade-out').style.display='block';
}

async function loadMarketPrices() { await callAndShow('market-out', 'GET', '/market/prices'); document.getElementById('market-out').style.display='block'; }
async function marketRecalculate() { await callAndShow('market-out', 'POST', '/market/recalculate', {}); document.getElementById('market-out').style.display='block'; }
async function marketBuy() {
  await callAndShow('market-out', 'POST', '/market/buy', {
    agent_id: document.getElementById('market-agent').value,
    item: document.getElementById('market-item').value,
    quantity: parseInt(document.getElementById('market-qty').value)
  });
  document.getElementById('market-out').style.display='block';
}
async function marketSell() {
  await callAndShow('market-out', 'POST', '/market/sell', {
    agent_id: document.getElementById('market-agent').value,
    item: document.getElementById('market-item').value,
    quantity: parseInt(document.getElementById('market-qty').value)
  });
  document.getElementById('market-out').style.display='block';
}

async function loadContracts() { await callAndShow('contract-out', 'GET', '/contracts'); document.getElementById('contract-out').style.display='block'; }
async function postContract() {
  await callAndShow('contract-out', 'POST', '/contracts', {
    requester_id: document.getElementById('contract-req').value,
    item: document.getElementById('contract-item').value,
    quantity: parseInt(document.getElementById('contract-qty').value),
    reward: parseInt(document.getElementById('contract-reward').value)
  });
  document.getElementById('contract-out').style.display='block';
}
async function fulfillContract() {
  await callAndShow('contract-out', 'POST', `/contracts/${document.getElementById('fulfill-contract-id').value}/fulfill`, {
    agent_id: document.getElementById('fulfill-agent-id').value
  });
  document.getElementById('contract-out').style.display='block';
}

// F20 GangWar
async function startGangWar() {
  await callAndShow('gw-out', 'POST', '/gangwar/start', { max_ticks: parseInt(document.getElementById('gw-ticks').value) || 300 });
  document.getElementById('gw-out').style.display='block';
}
async function stopGangWar() { await callAndShow('gw-out', 'POST', '/gangwar/stop', {}); document.getElementById('gw-out').style.display='block'; }
async function loadGangWarState() { await callAndShow('gw-out', 'GET', '/gangwar/state'); document.getElementById('gw-out').style.display='block'; }
async function sabotage() {
  await callAndShow('gw-out', 'POST', '/gangwar/sabotage', {
    agent_id: document.getElementById('sab-agent').value,
    target_gang: document.getElementById('sab-target').value
  });
  document.getElementById('gw-out').style.display='block';
}
async function bmBuy() {
  await callAndShow('gw-out', 'POST', '/gangwar/black-market/buy', {
    agent_id: document.getElementById('bm-buyer').value,
    item: document.getElementById('bm-item').value,
    quantity: 1
  });
  document.getElementById('gw-out').style.display='block';
}
async function loadBMPrices() { await callAndShow('gw-out', 'GET', '/gangwar/black-market/prices'); document.getElementById('gw-out').style.display='block'; }

// ══════════════════════════════════════════════════════
//  WEBHOOKS
// ══════════════════════════════════════════════════════
async function registerWebhook() {
  const evts = document.getElementById('wh-events').value.split(',').map(s => s.trim()).filter(Boolean);
  await callAndShow('wh-reg-out', 'POST', '/webhooks', {
    owner_id: document.getElementById('wh-owner').value,
    url: document.getElementById('wh-url').value,
    events: evts,
    secret: document.getElementById('wh-secret').value,
    max_retries: parseInt(document.getElementById('wh-retries').value) || 3
  });
  document.getElementById('wh-reg-out').style.display='block';
}
async function listWebhooks() {
  const owner = document.getElementById('wh-list-owner').value;
  await callAndShow('wh-list-out', 'GET', `/webhooks/${owner}`);
  document.getElementById('wh-list-out').style.display='block';
}
async function testWebhook() {
  const owner = document.getElementById('wh-list-owner').value;
  await callAndShow('wh-list-out', 'POST', '/webhooks/test', { owner_id: owner });
  document.getElementById('wh-list-out').style.display='block';
}
async function deleteWebhook() {
  const id = document.getElementById('wh-del-id').value;
  const owner = document.getElementById('wh-del-owner').value;
  try {
    const r = await fetch(BASE + `/webhooks/${id}?owner_id=${owner}`, { method: 'DELETE', headers: adminHeaders() });
    const d = await r.json();
    showOut('wh-list-out', d, !r.ok);
    document.getElementById('wh-list-out').style.display='block';
    toast(r.ok ? '✓ Deletado' : 'Erro', r.ok ? 'ok' : 'err');
  } catch (e) { toast('Erro: ' + e, 'err'); }
}
async function loadDeliveries() {
  const id = document.getElementById('wh-hist-id').value;
  const limit = document.getElementById('wh-hist-limit').value || 20;
  const qs = id ? `?webhook_id=${id}&limit=${limit}` : `?limit=${limit}`;
  await callAndShow('wh-hist-out', 'GET', `/webhooks/deliveries${qs}`);
  document.getElementById('wh-hist-out').style.display='block';
}
async function loadWebhookStats() { await callAndShow('wh-stats-out', 'GET', '/webhooks/admin/stats'); document.getElementById('wh-stats-out').style.display='block'; }
async function loadEventTypes() { await callAndShow('wh-stats-out', 'GET', '/webhooks/admin/event-types'); document.getElementById('wh-stats-out').style.display='block'; }

// ══════════════════════════════════════════════════════
//  BENCHMARK
// ══════════════════════════════════════════════════════
async function runAB() {
  await callAndShow('ab-out', 'POST', '/benchmarks/ab', {
    profile_a: document.getElementById('ab-profile-a').value,
    profile_b: document.getElementById('ab-profile-b').value,
    game_mode: document.getElementById('ab-mode').value,
    ticks: parseInt(document.getElementById('ab-ticks').value) || 200
  });
  document.getElementById('ab-out').style.display='block';
}
async function loadABResults() { await callAndShow('ab-out', 'GET', '/ab/results'); document.getElementById('ab-out').style.display='block'; }
async function loadABRun() {
  const id = document.getElementById('ab-run-id').value;
  await callAndShow('ab-report-out', 'GET', `/benchmarks/ab/${id}`);
  document.getElementById('ab-report-out').style.display='block';
}
async function loadABReport() {
  const id = document.getElementById('ab-run-id').value;
  await callAndShow('ab-report-out', 'GET', `/benchmarks/ab/${id}/report`);
  document.getElementById('ab-report-out').style.display='block';
}

async function createSeason() {
  await callAndShow('season-out', 'POST', '/seasons', { name: document.getElementById('season-name').value });
  document.getElementById('season-out').style.display='block';
}
async function loadSeasons() { await callAndShow('season-out', 'GET', '/seasons'); document.getElementById('season-out').style.display='block'; }
async function loadElo() {
  const pid = document.getElementById('elo-profile').value;
  await callAndShow('season-out', 'GET', `/elo/${pid}`);
  document.getElementById('season-out').style.display='block';
}

async function saveProfileVersion() {
  const pid = document.getElementById('ver-profile').value;
  const body = { note: document.getElementById('ver-note').value };
  const t = document.getElementById('ver-temp').value;
  if (t) body.temperature = parseFloat(t);
  await callAndShow('ver-out', 'POST', `/profiles/${pid}/versions`, body);
  document.getElementById('ver-out').style.display='block';
}
async function listProfileVersions() {
  const pid = document.getElementById('ver-profile').value;
  await callAndShow('ver-out', 'GET', `/profiles/${pid}/versions`);
  document.getElementById('ver-out').style.display='block';
}
async function activateVersion() {
  const pid = document.getElementById('ver-profile').value;
  const ver = document.getElementById('ver-activate-num').value;
  await callAndShow('ver-out', 'POST', `/profiles/${pid}/activate/${ver}`, {});
  document.getElementById('ver-out').style.display='block';
}

// ══════════════════════════════════════════════════════
//  AVANÇADO
// ══════════════════════════════════════════════════════
async function createTournament() {
  const profiles = document.getElementById('tourn-profiles').value.split(',').map(s => s.trim()).filter(Boolean);
  await callAndShow('tourn-out', 'POST', '/tournaments', {
    profiles, ticks: parseInt(document.getElementById('tourn-ticks').value) || 200
  });
  document.getElementById('tourn-out').style.display='block';
}
async function loadTournaments() { await callAndShow('tourn-out', 'GET', '/tournaments'); document.getElementById('tourn-out').style.display='block'; }

async function loadActiveEvents() { await callAndShow('event-out', 'GET', '/events/active'); document.getElementById('event-out').style.display='block'; }
async function loadEventHistory() { await callAndShow('event-out', 'GET', '/events/history'); document.getElementById('event-out').style.display='block'; }
async function loadEventTemplates() { await callAndShow('event-out', 'GET', '/events/templates'); document.getElementById('event-out').style.display='block'; }
async function triggerEvent() {
  await callAndShow('event-out', 'POST', '/events/trigger', { event_type: document.getElementById('trigger-event-type').value });
  document.getElementById('event-out').style.display='block';
}

async function assignMission() {
  const aid = document.getElementById('mission-agent').value;
  const mid = document.getElementById('mission-id').value;
  const body = { agent_id: aid };
  if (mid) body.mission_id = mid;
  await callAndShow('mission-out', 'POST', '/missions/assign', body);
  document.getElementById('mission-out').style.display='block';
}
async function loadMissionCatalog() { await callAndShow('mission-out', 'GET', '/missions/catalog'); document.getElementById('mission-out').style.display='block'; }
async function loadMissionsProgress() { await callAndShow('mission-out', 'GET', '/missions/progress'); document.getElementById('mission-out').style.display='block'; }
async function loadAgentMission() {
  const id = document.getElementById('mission-view-agent').value;
  await callAndShow('mission-out', 'GET', `/agents/${id}/mission`);
  document.getElementById('mission-out').style.display='block';
}

async function loadMemories() { await callAndShow('mem-out', 'GET', '/memories'); document.getElementById('mem-out').style.display='block'; }
async function saveMemory() {
  const id = document.getElementById('mem-agent').value;
  await callAndShow('mem-out', 'POST', `/memories/save/${id}`, {});
  document.getElementById('mem-out').style.display='block';
}
async function loadRateLimit() { await callAndShow('mem-out', 'GET', '/rate-limit/status'); document.getElementById('mem-out').style.display='block'; }

// ══════════════════════════════════════════════════════
//  GLOBAL REFRESH + BADGE
// ══════════════════════════════════════════════════════
async function pollModeBadge() {
  try {
    const d = await apiGet('/');
    const gm = d.game_mode || 'survival';
    // atualiza badge do header
    const badge = document.getElementById('mode-badge');
    if (badge) badge.textContent = gm;
    // sincroniza cards de modo
    document.querySelectorAll('.mode-card').forEach(c =>
      c.classList.toggle('selected', c.dataset.mode === gm)
    );
    selectedMode = gm;
    // atualiza banners de pré-requisito
    const wm = document.getElementById('prereq-warfare-mode');
    if (wm) {
      wm.textContent = gm;
      wm.style.color = gm === 'warfare' ? 'var(--success)' : 'var(--warn)';
    }
    const em = document.getElementById('prereq-econ-mode');
    if (em) {
      em.textContent = gm;
      em.style.color = ['economy','gangwar','hybrid'].includes(gm) ? 'var(--success)' : 'var(--warn)';
    }
    document.getElementById('ws-dot').className = 'ok';
  } catch {
    try {
      const d = await apiGet('/');
      const badge = document.getElementById('mode-badge');
      if (badge) badge.textContent = d.game_mode || '?';
      document.getElementById('ws-dot').className = 'ok';
    } catch { document.getElementById('ws-dot').className = ''; }
  }
}

function refreshAll() {
  loadServerStatus();
  pollModeBadge();
  loadAgents();
  toast('Atualizado!', 'info');
}

// ── Init ──────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('bbia_admin_token');
  const inp = document.getElementById('token-input');
  if (saved && inp) inp.value = saved;
  // salvar automaticamente ao digitar ou sair do campo
  if (inp) {
    inp.addEventListener('change', () => {
      const v = inp.value.trim();
      if (v) { localStorage.setItem('bbia_admin_token', v); highlightToken(false); }
    });
    inp.addEventListener('input', () => highlightToken(false));
  }
  loadServerStatus();
  pollModeBadge();
  loadAgents();
  setInterval(pollModeBadge, 5000);
});

// breakAlliance needs DELETE method
async function breakAlliance() {
  const id = document.getElementById('ally-agent-id').value;
  try {
    const r = await fetch(BASE + `/agents/${id}/alliance`, { method: 'DELETE', headers: adminHeaders() });
    const d = await r.json();
    showOut('ally-out', d, !r.ok);
    document.getElementById('ally-out').style.display='block';
    toast(r.ok ? '✓ Aliança quebrada' : 'Erro: ' + d.detail, r.ok ? 'ok' : 'err');
  } catch (e) { toast('Erro: ' + e, 'err'); }
}
