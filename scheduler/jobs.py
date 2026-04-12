"""
APScheduler — trabajos programados de JARVIS.

Todos los jobs comparten el grafo LangGraph y el bot de Telegram.
El scheduler corre en el mismo event loop que el bot (AsyncIOScheduler).
"""

from __future__ import annotations

import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings


def build_scheduler(graph, bot) -> AsyncIOScheduler:
    tz = settings.schedule.timezone
    scheduler = AsyncIOScheduler(timezone=tz)

    # ── Resumen de noticias diario ────────────────────────────────────────
    scheduler.add_job(
        _send_news_digest,
        CronTrigger(
            hour=settings.schedule.news_digest_hour,
            minute=settings.schedule.news_digest_minute,
            timezone=tz,
        ),
        args=[graph, bot],
        id="daily_news",
        replace_existing=True,
    )

    # ── Post de LinkedIn semanal ──────────────────────────────────────────
    scheduler.add_job(
        _trigger_linkedin,
        CronTrigger(
            day_of_week=settings.schedule.linkedin_post_day,
            hour=settings.schedule.linkedin_post_hour,
            minute=0,
            timezone=tz,
        ),
        args=[graph, bot],
        id="weekly_linkedin",
        replace_existing=True,
    )

    # ── Backup diario de fotos ────────────────────────────────────────────
    scheduler.add_job(
        _run_backup,
        CronTrigger(
            hour=settings.schedule.backup_hour,
            minute=0,
            timezone=tz,
        ),
        args=[graph, bot],
        id="daily_backup",
        replace_existing=True,
    )

    return scheduler


def _owner_chat_id() -> int | None:
    ids = settings.telegram_allowed_user_ids
    return ids[0] if ids else None


async def _send_news_digest(graph, bot) -> None:
    from core.state import initial_state
    from loguru import logger

    chat_id = _owner_chat_id()
    if not chat_id:
        logger.warning("No hay telegram_allowed_user_ids configurado — saltando news digest")
        return

    logger.info("Ejecutando job: daily_news")
    state = initial_state("Dame el resumen de noticias de hoy", chat_id)
    state["next_agent"] = "news"
    config = {"configurable": {"thread_id": f"news_sched_{uuid.uuid4().hex[:8]}"}}

    try:
        result = await graph.ainvoke(state, config=config)
        digest = result.get("news_digest", [])

        if digest:
            lines = ["📰 *Resumen de noticias*\n"]
            for item in digest[:10]:
                lines.append(f"• [{item.get('title', '?')}]({item.get('url', '')})")
            text = "\n".join(lines)
        else:
            # Fallback: último mensaje AI
            text = "📰 Resumen de noticias listo."
            for msg in reversed(result.get("messages", [])):
                if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
                    text = msg.content
                    break

        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown",
                               disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Error en job daily_news: {}", e)


async def _trigger_linkedin(graph, bot) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.state import initial_state
    from loguru import logger

    chat_id = _owner_chat_id()
    if not chat_id:
        return

    logger.info("Ejecutando job: weekly_linkedin")
    thread_id = f"linkedin_sched_{uuid.uuid4().hex[:8]}"
    state = initial_state(
        "Crea un post de LinkedIn sobre tendencias en IA y productividad personal",
        chat_id,
    )
    state["next_agent"] = "linkedin"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await graph.ainvoke(state, config=config)

        if result.get("awaiting_human") and result.get("linkedin_draft"):
            draft = result["linkedin_draft"]
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Publicar", callback_data=f"linkedin:approve:{thread_id}"),
                    InlineKeyboardButton("❌ Descartar", callback_data=f"linkedin:reject:{thread_id}"),
                ],
                [InlineKeyboardButton("✏️ Editar", callback_data=f"linkedin:edit:{thread_id}")],
            ])
            await bot.send_message(
                chat_id=chat_id,
                text=f"📝 *Borrador de LinkedIn (programado):*\n\n{draft}",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
    except Exception as e:
        logger.exception("Error en job weekly_linkedin: {}", e)
        await bot.send_message(chat_id=chat_id, text=f"❌ Error generando post LinkedIn: {e}")


async def _run_backup(graph, bot) -> None:
    from core.state import initial_state
    from loguru import logger

    chat_id = _owner_chat_id()
    if not chat_id:
        return

    logger.info("Ejecutando job: daily_backup")
    state = initial_state("Haz backup de las fotos de hoy", chat_id)
    state["next_agent"] = "icloud"
    config = {"configurable": {"thread_id": f"backup_sched_{uuid.uuid4().hex[:8]}"}}

    try:
        result = await graph.ainvoke(state, config=config)
        backup_res = result.get("backup_result", {})

        if backup_res.get("success"):
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Backup diario completado\n📁 `{backup_res.get('exported_to', '?')}`",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.exception("Error en job daily_backup: {}", e)
