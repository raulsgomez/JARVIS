"""
Handler del comando /cost — muestra el desglose de costes de LLM.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


def _fmt(val: float) -> str:
    """Formatea un float como dólares."""
    if val == 0.0:
        return "$0.00"
    if val < 0.01:
        return f"${val:.5f}"
    return f"${val:.4f}"


async def cost_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.bot_data["services"]
    data = await services.cost_tracker.summary()

    lines = [
        "💸 *JARVIS — Coste de IA*",
        "",
        f"*Hoy:*      {_fmt(data['today_usd'])}",
        f"*Este mes:* {_fmt(data['month_usd'])}",
        f"*Total:*    {_fmt(data['total_usd'])}",
    ]

    if data["by_agent"]:
        lines += ["", "*Por agente:*"]
        for row in data["by_agent"]:
            agent, cost, t_in, t_out, calls = row
            lines.append(
                f"  `{agent:<12}` {_fmt(cost):>10}  "
                f"({t_in:,}↑ {t_out:,}↓ | {calls} calls)"
            )

    if data["by_model"]:
        lines += ["", "*Por modelo:*"]
        for row in data["by_model"]:
            model, cost, t_in, t_out = row
            lines.append(f"  `{model:<28}` {_fmt(cost):>10}")

    if data["errors_today"] > 0:
        lines += ["", f"⚠️ Errores hoy: {int(data['errors_today'])}"]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
