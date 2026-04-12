"""
CostTracker — persiste y consulta el coste de llamadas LLM.

Escribe en SQLite de forma asíncrona.
Se consulta via /cost en Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CallRecord:
    agent_name: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    session_id: str | None = None
    error: str | None = None


class CostTracker:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def init_db(self) -> None:
        """Crea la tabla si no existe."""
        import aiosqlite

        schema = Path(__file__).parent / "schema.sql"
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(schema.read_text())
            await db.commit()

    async def log(self, record: CallRecord) -> None:
        """Inserta un registro de llamada LLM."""
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO llm_cost_log
                   (agent_name, model, tokens_in, tokens_out, cost_usd, session_id, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.agent_name,
                    record.model,
                    record.tokens_in,
                    record.tokens_out,
                    record.cost_usd,
                    record.session_id,
                    record.error,
                ),
            )
            await db.commit()

    async def summary(self) -> dict:
        """Resumen de costes para el comando /cost de Telegram."""
        import aiosqlite

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        async with aiosqlite.connect(self._db_path) as db:
            async def scalar(sql: str, params: tuple = ()) -> float:
                cur = await db.execute(sql, params)
                row = await cur.fetchone()
                return float(row[0] or 0.0)

            async def rows(sql: str, params: tuple = ()) -> list:
                cur = await db.execute(sql, params)
                return await cur.fetchall()

            return {
                "today_usd": await scalar(
                    "SELECT SUM(cost_usd) FROM llm_cost_log WHERE timestamp LIKE ?",
                    (f"{today}%",),
                ),
                "month_usd": await scalar(
                    "SELECT SUM(cost_usd) FROM llm_cost_log WHERE timestamp LIKE ?",
                    (f"{month}%",),
                ),
                "total_usd": await scalar(
                    "SELECT SUM(cost_usd) FROM llm_cost_log",
                ),
                "by_agent": await rows(
                    """SELECT agent_name,
                              SUM(cost_usd)   AS cost,
                              SUM(tokens_in)  AS tin,
                              SUM(tokens_out) AS tout,
                              COUNT(*)        AS calls
                       FROM llm_cost_log
                       GROUP BY agent_name
                       ORDER BY cost DESC"""
                ),
                "by_model": await rows(
                    """SELECT model,
                              SUM(cost_usd)   AS cost,
                              SUM(tokens_in)  AS tin,
                              SUM(tokens_out) AS tout
                       FROM llm_cost_log
                       GROUP BY model
                       ORDER BY cost DESC"""
                ),
                "errors_today": await scalar(
                    "SELECT COUNT(*) FROM llm_cost_log WHERE timestamp LIKE ? AND error IS NOT NULL",
                    (f"{today}%",),
                ),
            }
