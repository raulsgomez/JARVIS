-- Tabla de log de llamadas LLM para cost tracking
CREATE TABLE IF NOT EXISTS llm_cost_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    agent_name  TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL    NOT NULL DEFAULT 0.0,
    session_id  TEXT,
    error       TEXT    -- NULL si éxito, mensaje de error si falla
);

CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON llm_cost_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_agent     ON llm_cost_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_cost_model     ON llm_cost_log(model);
