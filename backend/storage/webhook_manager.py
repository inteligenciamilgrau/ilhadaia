"""
F11 — Webhooks Expandidos (T24 melhorado)

Novos tipos de evento: session_start, session_end, agent_dead, winner_declared,
  tournament_end, checkpoint_captured, artifact_delivered, sabotage, gangwar_end,
  gincana_end, warfare_end, contract_fulfilled, trade, market_buy, market_sell

Retry configurável: max_retries (default 3), backoff exponencial de 2s → 4s → 8s

Histórico de entregas: tabela webhook_deliveries com status, tentativa e resposta
"""
import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("BBB_IA.WebhookManager")

# ─── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhooks (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    url         TEXT NOT NULL,
    events      TEXT NOT NULL,
    secret      TEXT DEFAULT '',
    max_retries INTEGER DEFAULT 3,
    created_at  REAL NOT NULL,
    last_fired  REAL,
    fire_count  INTEGER DEFAULT 0,
    fail_count  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    attempt     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL,      -- 'ok', 'fail', 'retry'
    http_code   INTEGER,
    error       TEXT,
    fired_at    REAL NOT NULL
);
"""

VALID_EVENTS = {
    # Originais
    "death", "win", "zombie", "tournament_end", "agent_registered", "test", "all",
    # F11 — Novos eventos
    "session_start", "session_end", "agent_dead", "winner_declared",
    "checkpoint_captured", "artifact_delivered", "sabotage",
    "gangwar_end", "gincana_end", "warfare_end",
    "contract_fulfilled", "trade", "market_buy", "market_sell",
}


class WebhookManager:
    """Gerencia registros de webhooks e disparo de notificações HTTP (F11 expandido)."""

    DEFAULT_MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0   # segundos de espera no primeiro retry

    def __init__(self, db_path: str = "data/ilhadaia.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._migrate()
        self._http_client = None  # lazy init

    def _migrate(self) -> None:
        """Aplica migrações incrementais seguras para compatibilidade com schema antigo."""
        migrations = [
            "ALTER TABLE webhooks ADD COLUMN fail_count INTEGER DEFAULT 0",
            "ALTER TABLE webhooks ADD COLUMN max_retries INTEGER DEFAULT 3",
        ]
        for stmt in migrations:
            try:
                self.conn.execute(stmt)
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # coluna/tabela já existe

    # ── Registro ──────────────────────────────────────────────────────────────

    def register(self, owner_id: str, url: str, events: list[str],
                 secret: str = "", max_retries: int = DEFAULT_MAX_RETRIES) -> dict:
        """Registra (ou atualiza) um webhook para o owner."""
        valid = [e for e in events if e in VALID_EVENTS]
        if not valid:
            valid = ["all"]
        retries = max(0, min(max_retries, 5))  # clamp 0–5
        wid = f"wh_{owner_id}_{int(time.time())}"
        self.conn.execute(
            """INSERT OR REPLACE INTO webhooks
               (id, owner_id, url, events, secret, max_retries, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (wid, owner_id, url, json.dumps(valid), secret, retries, time.time()),
        )
        self.conn.commit()
        logger.info(f"Webhook registered: {wid} for {owner_id} → {url} (events={valid}, retries={retries})")
        return {"webhook_id": wid, "owner_id": owner_id, "url": url,
                "events": valid, "max_retries": retries}

    def list_for_owner(self, owner_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, url, events, created_at, fire_count, fail_count, max_retries FROM webhooks WHERE owner_id=?",
            (owner_id,),
        ).fetchall()
        return [
            {"id": r[0], "url": r[1], "events": json.loads(r[2]),
             "created_at": r[3], "fire_count": r[4], "fail_count": r[5], "max_retries": r[6]}
            for r in rows
        ]

    def delete(self, webhook_id: str, owner_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM webhooks WHERE id=? AND owner_id=?", (webhook_id, owner_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── Disparo ───────────────────────────────────────────────────────────────

    async def fire_event(self, event_type: str, payload: dict) -> int:
        """
        Dispara o evento para todos os webhooks registrados para esse tipo.
        Retorna o número de webhooks notificados com sucesso.
        """
        hooks = self._get_hooks_for_event(event_type)
        if not hooks:
            return 0
        tasks = [self._send_with_retry(hook, event_type, payload) for hook in hooks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        fired = sum(1 for r in results if r is True)
        return fired

    def _get_hooks_for_event(self, event_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, owner_id, url, events, secret, max_retries FROM webhooks"
        ).fetchall()
        result = []
        for row in rows:
            events = json.loads(row[3])
            if "all" in events or event_type in events:
                result.append({
                    "id": row[0], "owner_id": row[1], "url": row[2],
                    "events": events, "secret": row[4], "max_retries": row[5]
                })
        return result

    async def _send_with_retry(self, hook: dict, event_type: str, payload: dict) -> bool:
        """Tenta enviar até max_retries vezes com backoff exponencial."""
        max_retries = hook.get("max_retries", self.DEFAULT_MAX_RETRIES)
        for attempt in range(1, max_retries + 2):  # attempt 1..max_retries+1
            ok, code, err = await self._send(hook, event_type, payload)
            status = "ok" if ok else ("retry" if attempt <= max_retries else "fail")
            self._log_delivery(hook["id"], event_type, attempt, status, code, err)
            if ok:
                self.conn.execute(
                    "UPDATE webhooks SET last_fired=?, fire_count=fire_count+1 WHERE id=?",
                    (time.time(), hook["id"]),
                )
                self.conn.commit()
                return True
            if attempt <= max_retries:
                delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 2s, 4s, 8s…
                logger.info(f"Webhook {hook['id']} retry {attempt}/{max_retries} in {delay:.0f}s")
                await asyncio.sleep(delay)
        # Esgotou retries
        self.conn.execute(
            "UPDATE webhooks SET fail_count=fail_count+1 WHERE id=?",
            (hook["id"],),
        )
        self.conn.commit()
        return False

    async def _send(self, hook: dict, event_type: str, payload: dict) -> tuple[bool, Optional[int], Optional[str]]:
        """Envia POST único. Retorna (success, http_code, error_str)."""
        try:
            import httpx
            body = json.dumps({
                "event": event_type,
                "timestamp": time.time(),
                "payload": payload,
            }, ensure_ascii=False)

            headers = {"Content-Type": "application/json"}
            if hook.get("secret"):
                sig = hmac.new(
                    hook["secret"].encode(), body.encode(), hashlib.sha256
                ).hexdigest()
                headers["X-BBBia-Signature"] = f"sha256={sig}"

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(hook["url"], content=body, headers=headers)

            logger.info(f"Webhook {hook['id']} fired → {hook['url']} ({resp.status_code})")
            return (resp.status_code < 400, resp.status_code, None)

        except ImportError:
            logger.warning(f"httpx not installed, webhook {hook['id']} skipped")
            return (False, None, "httpx_not_installed")
        except Exception as e:
            logger.warning(f"Webhook {hook['id']} failed: {e}")
            return (False, None, str(e))

    def _log_delivery(self, webhook_id: str, event_type: str, attempt: int,
                      status: str, http_code: Optional[int], error: Optional[str]) -> None:
        """Persiste registro na tabela webhook_deliveries."""
        try:
            self.conn.execute(
                """INSERT INTO webhook_deliveries (webhook_id, event_type, attempt, status, http_code, error, fired_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (webhook_id, event_type, attempt, status, http_code, error, time.time())
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to log delivery: {e}")

    # ── Histórico ─────────────────────────────────────────────────────────────

    def get_delivery_history(self, webhook_id: str = None, limit: int = 50) -> list[dict]:
        """Retorna histórico de entregas, filtrado por webhook_id se fornecido."""
        if webhook_id:
            rows = self.conn.execute(
                """SELECT id, webhook_id, event_type, attempt, status, http_code, error, fired_at
                   FROM webhook_deliveries WHERE webhook_id=? ORDER BY fired_at DESC LIMIT ?""",
                (webhook_id, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT id, webhook_id, event_type, attempt, status, http_code, error, fired_at
                   FROM webhook_deliveries ORDER BY fired_at DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        cols = ["id", "webhook_id", "event_type", "attempt", "status", "http_code", "error", "fired_at"]
        return [dict(zip(cols, r)) for r in rows]

    def get_delivery_stats(self) -> dict:
        """Estatísticas gerais de disparo."""
        total = self.conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0]
        ok = self.conn.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE status='ok'").fetchone()[0]
        fail = self.conn.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE status='fail'").fetchone()[0]
        by_event = self.conn.execute(
            "SELECT event_type, COUNT(*) FROM webhook_deliveries GROUP BY event_type ORDER BY COUNT(*) DESC"
        ).fetchall()
        return {
            "total_attempts": total,
            "success": ok,
            "failures": fail,
            "success_rate": round(ok / total * 100, 1) if total > 0 else 0,
            "by_event_type": {row[0]: row[1] for row in by_event},
        }

    def close(self) -> None:
        self.conn.close()
