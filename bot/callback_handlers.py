"""
Callback handlers para botones inline de Telegram.

Maneja la aprobación/rechazo de posts de LinkedIn
reanudando el grafo LangGraph desde el checkpoint.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


async def linkedin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja los botones [✅ Publicar] [❌ Descartar] [✏️ Editar] del draft de LinkedIn.

    Reanuda el grafo suspendido pasando la decisión del usuario via Command(resume=...).
    """
    from langgraph.types import Command

    query = update.callback_query
    await query.answer()  # Elimina el "loading" del botón

    # Parsear callback_data: "linkedin:approve:THREAD_ID"
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        await query.edit_message_text("❌ Callback inválido.")
        return

    _, action, thread_id = parts
    graph = context.bot_data["graph"]
    config = {"configurable": {"thread_id": thread_id}}

    if action == "approve":
        from loguru import logger
        await query.edit_message_text("⏳ Publicando en LinkedIn...")
        result = await graph.ainvoke(Command(resume="approve"), config=config)

        logger.debug("[linkedin_callback] result keys: {}", list(result.keys()))
        logger.debug("[linkedin_callback] __interrupt__: {}", result.get("__interrupt__"))

        # Si el graph volvió a suspenderse (resume no funcionó), informar
        if result.get("__interrupt__"):
            logger.error("[linkedin_callback] El graph se suspendió de nuevo — resume falló")
            await query.edit_message_text("❌ Error interno: el graph no reanudó correctamente. Intenta de nuevo.")
            return

        # Buscar el mensaje de resultado del agente linkedin
        final_msg = ""
        for msg in reversed(result.get("messages", [])):
            content = getattr(msg, "content", "")
            if content and getattr(msg, "name", "") == "linkedin":
                final_msg = content
                break
        if not final_msg:
            final_msg = "✅ Operación completada."
        await query.edit_message_text(final_msg)

    elif action == "reject":
        await query.edit_message_text("❌ Post descartado.")
        await graph.ainvoke(Command(resume="reject"), config=config)

    elif action == "edit":
        await query.edit_message_text(
            "✏️ Respóndeme con tu feedback y generaré una nueva versión."
        )
        # El feedback llegará como mensaje de texto en el próximo turno.
        # Guardamos el thread_id en user_data para recuperarlo.
        context.user_data["pending_linkedin_thread"] = thread_id

    else:
        await query.edit_message_text("❌ Acción desconocida.")
