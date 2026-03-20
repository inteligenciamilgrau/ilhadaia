"""
Session Store — persiste sessões, scores históricos e metadados de replay em SQLite WAL.
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from runtime.profiles import get_profile


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    world_settings TEXT,
    winner_agent_id TEXT,
    winner_model    TEXT,
    game_mode   TEXT DEFAULT 'survival',
    status      TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS agent_scores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT REFERENCES sessions(id),
    agent_id            TEXT NOT NULL,
    agent_name          TEXT NOT NULL,
    owner_id            TEXT DEFAULT '',
    model               TEXT DEFAULT 'kr/claude-sonnet-4.5',
    provider            TEXT DEFAULT 'omnirouter',
    profile_id          TEXT DEFAULT 'default',
    ticks_alive         INTEGER DEFAULT 0,
    score_survival      REAL DEFAULT 0,
    score_social        REAL DEFAULT 0,
    score_efficiency    REAL DEFAULT 0,
    score_total         REAL DEFAULT 0,
    tokens_used         INTEGER DEFAULT 0,
    cost_usd            REAL DEFAULT 0,
    decisions_made      INTEGER DEFAULT 0,
    invalid_actions     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS world_settings_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at  REAL NOT NULL,
    settings    TEXT NOT NULL
);

-- ── F06 — Temporadas e ELO ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS seasons (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    status      TEXT DEFAULT 'active',   -- active | completed
    game_mode   TEXT DEFAULT 'survival',
    description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS elo_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id   TEXT REFERENCES seasons(id),
    session_id  TEXT REFERENCES sessions(id),
    profile_id  TEXT NOT NULL,
    elo_before  REAL NOT NULL,
    elo_after   REAL NOT NULL,
    delta       REAL NOT NULL,
    placement   INTEGER NOT NULL,    -- 1=winner, 2=second, etc.
    score_total REAL DEFAULT 0,
    recorded_at REAL NOT NULL
);

-- ── F02 — Comparador A/B ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ab_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,       -- UUID da rodada A/B
    session_id  TEXT REFERENCES sessions(id),
    profile_a   TEXT NOT NULL,
    profile_b   TEXT NOT NULL,
    winner      TEXT,                -- 'A' | 'B' | 'tie'
    score_a     REAL DEFAULT 0,
    score_b     REAL DEFAULT 0,
    ticks_a     INTEGER DEFAULT 0,
    ticks_b     INTEGER DEFAULT 0,
    tokens_a    INTEGER DEFAULT 0,
    tokens_b    INTEGER DEFAULT 0,
    game_mode   TEXT DEFAULT 'survival',
    recorded_at REAL NOT NULL
);

-- ── F09 — Versionamento de Perfis ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profile_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    snapshot    TEXT NOT NULL,       -- JSON: {model, temperature, max_tokens, token_budget, cooldown_ticks, system_prompt_override}
    note        TEXT DEFAULT '',
    created_at  REAL NOT NULL,
    created_by  TEXT DEFAULT 'system'
);
"""



class SessionStore:
    """SQLite-backed store para sessões e scoreboard histórico."""

    def __init__(self, db_path: str = "data/ilhadaia.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        # Migration: adicionar colunas que podem não existir em DBs antigos
        self._migrate()

    def _migrate(self) -> None:
        """Aplica migrations incrementais para colunas novas sem recriar o schema."""
        migrations = [
            ("sessions", "game_mode", "TEXT DEFAULT 'survival'"),
        ]
        for table, col, col_def in migrations:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                self.conn.commit()
            except sqlite3.OperationalError:
                # Coluna já existe — ignorar
                pass

    # ── Sessions ────────────────────────────────────────────────────────────

    def create_session(self, world_settings: dict, game_mode: str = "survival") -> str:
        session_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO sessions (id, started_at, world_settings, game_mode, status) VALUES (?, ?, ?, ?, 'active')",
            (session_id, time.time(), json.dumps(world_settings), game_mode),
        )
        self.conn.commit()
        return session_id

    def end_session(self, session_id: str, winner_id: Optional[str],
                    winner_model: Optional[str]) -> None:
        self.conn.execute(
            """UPDATE sessions
               SET ended_at = ?, winner_agent_id = ?, winner_model = ?, status = 'completed'
               WHERE id = ?""",
            (time.time(), winner_id, winner_model, session_id),
        )
        self.conn.commit()

    def get_sessions(self, limit: int = 20) -> list[dict]:
        cur = self.conn.execute(
            """SELECT id, started_at, ended_at, winner_model, game_mode, status
               FROM sessions ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── Agent Scores ─────────────────────────────────────────────────────────

    def upsert_agent_score(self, session_id: str, agent) -> None:
        """Insere ou atualiza o score de um agente na sessão atual."""
        benchmark = getattr(agent, "benchmark", {})
        existing = self.conn.execute(
            "SELECT id FROM agent_scores WHERE session_id=? AND agent_id=?",
            (session_id, agent.id),
        ).fetchone()

        if existing:
            self.conn.execute(
                """UPDATE agent_scores SET
                   ticks_alive=?, score_total=?, tokens_used=?,
                   cost_usd=?, decisions_made=?, invalid_actions=?
                   WHERE session_id=? AND agent_id=?""",
                (
                    benchmark.get("ticks_survived", 0),
                    benchmark.get("score", 0.0),
                    getattr(agent, "tokens_used", 0),
                    benchmark.get("cost_usd", 0.0),
                    benchmark.get("decisions_made", 0),
                    benchmark.get("invalid_actions", 0),
                    session_id, agent.id,
                ),
            )
        else:
            profile_id = getattr(agent, "profile_id", "default")
            profile = get_profile(profile_id)
            self.conn.execute(
                """INSERT INTO agent_scores
                   (session_id, agent_id, agent_name, owner_id, model, provider,
                    profile_id, ticks_alive, score_total, tokens_used, cost_usd,
                    decisions_made, invalid_actions)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id, agent.id, agent.name,
                    getattr(agent, "owner_id", ""),
                    profile.model,
                    profile.provider,
                    profile_id,
                    benchmark.get("ticks_survived", 0),
                    benchmark.get("score", 0.0),
                    getattr(agent, "tokens_used", 0),
                    benchmark.get("cost_usd", 0.0),
                    benchmark.get("decisions_made", 0),
                    benchmark.get("invalid_actions", 0),
                ),
            )
        self.conn.commit()

    def get_scoreboard(self, limit: int = 50) -> list[dict]:
        cur = self.conn.execute(
            """SELECT agent_name, model, provider, profile_id,
                      score_total, tokens_used, cost_usd, decisions_made
               FROM agent_scores
               ORDER BY score_total DESC LIMIT ?""",
            (limit,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── F06 — Temporadas e ELO ────────────────────────────────────────────────

    # ELO padrão para novos perfis
    ELO_DEFAULT = 1000.0
    ELO_K = 32  # Fator K (sensibilidade do ELO)

    def create_season(self, name: str, game_mode: str = "survival",
                      description: str = "") -> str:
        """Cria uma nova temporada. Retorna o ID."""
        sid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO seasons (id, name, started_at, game_mode, description) VALUES (?, ?, ?, ?, ?)",
            (sid, name, time.time(), game_mode, description),
        )
        self.conn.commit()
        return sid

    def end_season(self, season_id: str) -> None:
        self.conn.execute(
            "UPDATE seasons SET ended_at=?, status='completed' WHERE id=?",
            (time.time(), season_id),
        )
        self.conn.commit()

    def get_seasons(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, name, started_at, ended_at, status, game_mode, description FROM seasons ORDER BY started_at DESC"
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_elo(self, season_id: str, profile_id: str) -> float:
        """Retorna o ELO atual de um perfil na temporada. Usa ELO_DEFAULT se não existir."""
        row = self.conn.execute(
            "SELECT elo_after FROM elo_history WHERE season_id=? AND profile_id=? ORDER BY id DESC LIMIT 1",
            (season_id, profile_id),
        ).fetchone()
        return row[0] if row else self.ELO_DEFAULT

    def _calc_elo(self, ratings: list[float]) -> list[float]:
        """Calcula novo ELO para N jogadores ranqueados do 1° ao N°.
        Cada par (i,j) é tratado como um match: i venceu j se i < j (menor placement = melhor)."""
        n = len(ratings)
        deltas = [0.0] * n
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                expected_i = 1 / (1 + 10 ** ((ratings[j] - ratings[i]) / 400))
                actual_i = 1.0 if i < j else 0.0
                deltas[i] += self.ELO_K * (actual_i - expected_i)
        return [ratings[i] + deltas[i] for i in range(n)]

    def record_elo_session(self, season_id: str, session_id: str,
                           placements: list[dict]) -> list[dict]:
        """Registra o resultado de ELO de uma sessão.
        placements: lista ordenada de {profile_id, score_total} do 1° ao último.
        Retorna lista de {profile_id, elo_before, elo_after, delta}.
        """
        now = time.time()
        profile_ids = [p["profile_id"] for p in placements]
        elos_before = [self.get_elo(season_id, pid) for pid in profile_ids]
        elos_after = self._calc_elo(elos_before)

        results = []
        for i, (pid, eb, ea) in enumerate(zip(profile_ids, elos_before, elos_after)):
            delta = ea - eb
            self.conn.execute(
                """INSERT INTO elo_history
                   (season_id, session_id, profile_id, elo_before, elo_after, delta, placement, score_total, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (season_id, session_id, pid, eb, ea, delta, i + 1,
                 placements[i].get("score_total", 0), now),
            )
            results.append({"profile_id": pid, "elo_before": eb, "elo_after": round(ea, 1), "delta": round(delta, 1), "placement": i + 1})
        self.conn.commit()
        return results

    def get_leaderboard_elo(self, season_id: str) -> list[dict]:
        """Retorna o leaderboard de ELO atual para uma temporada."""
        cur = self.conn.execute(
            """SELECT eh.profile_id,
                      eh.elo_after AS elo,
                      eh.placement,
                      eh.score_total,
                      eh.recorded_at
               FROM elo_history AS eh
               JOIN (
                   SELECT profile_id, MAX(id) AS max_id
                   FROM elo_history
                   WHERE season_id=?
                   GROUP BY profile_id
               ) AS latest
                 ON eh.profile_id = latest.profile_id
                AND eh.id = latest.max_id
               WHERE eh.season_id=?
               ORDER BY elo DESC""",
            (season_id, season_id),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── F02 — Comparador A/B ──────────────────────────────────────────────────

    def record_ab_result(self, run_id: str, session_id: str,
                         profile_a: str, profile_b: str,
                         score_a: float, score_b: float,
                         ticks_a: int, ticks_b: int,
                         tokens_a: int, tokens_b: int,
                         game_mode: str = "survival") -> dict:
        """Persiste o resultado de uma comparação A/B entre dois perfis."""
        winner = "tie"
        if score_a > score_b:
            winner = "A"
        elif score_b > score_a:
            winner = "B"
        self.conn.execute(
            """INSERT INTO ab_results
               (run_id, session_id, profile_a, profile_b, winner,
                score_a, score_b, ticks_a, ticks_b, tokens_a, tokens_b,
                game_mode, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, session_id, profile_a, profile_b, winner,
             score_a, score_b, ticks_a, ticks_b, tokens_a, tokens_b,
             game_mode, time.time()),
        )
        self.conn.commit()
        return {"run_id": run_id, "winner": winner, "profile_a": profile_a, "profile_b": profile_b,
                "score_a": score_a, "score_b": score_b}

    def get_ab_summary(self, profile_a: str = None, profile_b: str = None,
                       limit: int = 50) -> list[dict]:
        """Retorna resultados A/B. Filtra por perfil se fornecido."""
        if profile_a and profile_b:
            cur = self.conn.execute(
                """SELECT * FROM ab_results WHERE (profile_a=? AND profile_b=?) OR (profile_a=? AND profile_b=?)
                   ORDER BY recorded_at DESC LIMIT ?""",
                (profile_a, profile_b, profile_b, profile_a, limit),
            )
        elif profile_a:
            cur = self.conn.execute(
                "SELECT * FROM ab_results WHERE profile_a=? OR profile_b=? ORDER BY recorded_at DESC LIMIT ?",
                (profile_a, profile_a, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM ab_results ORDER BY recorded_at DESC LIMIT ?",
                (limit,),
            )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_ab_stats(self) -> list[dict]:
        """Retorna estatísticas agregadas por par de perfis (wins/losses/ties)."""
        cur = self.conn.execute(
            """SELECT profile_a, profile_b,
                      COUNT(*) as total,
                      SUM(CASE WHEN winner='A' THEN 1 ELSE 0 END) as wins_a,
                      SUM(CASE WHEN winner='B' THEN 1 ELSE 0 END) as wins_b,
                      SUM(CASE WHEN winner='tie' THEN 1 ELSE 0 END) as ties,
                      AVG(score_a) as avg_score_a,
                      AVG(score_b) as avg_score_b,
                      AVG(tokens_a) as avg_tokens_a,
                      AVG(tokens_b) as avg_tokens_b
               FROM ab_results GROUP BY profile_a, profile_b"""
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── F09 — Versionamento de Perfis ─────────────────────────────────────────

    def save_profile_version(self, profile_id: str, snapshot: dict,
                             note: str = "", created_by: str = "system") -> int:
        """Salva versão nova de um perfil. Retorna o número da versão."""
        row = self.conn.execute(
            "SELECT MAX(version) FROM profile_versions WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        next_version = (row[0] or 0) + 1
        self.conn.execute(
            """INSERT INTO profile_versions (profile_id, version, snapshot, note, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (profile_id, next_version, json.dumps(snapshot), note, time.time(), created_by),
        )
        self.conn.commit()
        return next_version

    def get_profile_versions(self, profile_id: str) -> list[dict]:
        """Retorna o histórico de versões de um perfil."""
        cur = self.conn.execute(
            "SELECT id, profile_id, version, snapshot, note, created_at, created_by FROM profile_versions WHERE profile_id=? ORDER BY version DESC",
            (profile_id,),
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        for r in rows:
            try:
                r["snapshot"] = json.loads(r["snapshot"])
            except Exception:
                pass
        return rows

    def get_profile_versions_all(self) -> list[dict]:
        """Retorna todas as versões de todos os perfis (para listagem global)."""
        cur = self.conn.execute(
            "SELECT id, profile_id, version, note, created_at, created_by FROM profile_versions ORDER BY created_at DESC LIMIT 100"
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def rollback_profile_version(self, profile_id: str, version: int) -> Optional[dict]:
        """Retorna o snapshot de uma versão específica para rollback."""
        row = self.conn.execute(
            "SELECT snapshot FROM profile_versions WHERE profile_id=? AND version=?",
            (profile_id, version),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def close(self) -> None:
        self.conn.close()

