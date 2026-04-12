"""
Telegram Bot — configura la Application y registra handlers.

Usa polling mode (sin webhook) — perfecto para uso personal en red local.
Todos los handlers aplican whitelist de user_id antes de procesar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config.settings import settings

if TYPE_CHECKING:
    from core.services import ServiceContainer


def build_application(services: ServiceContainer) -> Application:
    """
    Construye la Application de python-telegram-bot.
    Inyecta services en bot_data para que los handlers lo accedan.
    """
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Inyectar services en el contexto del bot
    app.bot_data["services"] = services

    # Filtro de whitelist — solo responde al propietario
    if settings.telegram_allowed_user_ids:
        whitelist = filters.User(user_id=settings.telegram_allowed_user_ids)
    else:
        # Sin whitelist configurada: loguear advertencia y aceptar todos
        from loguru import logger
        logger.warning(
            "⚠️  telegram.allowed_user_ids vacío en settings.yaml. "
            "El bot responderá a cualquier usuario."
        )
        whitelist = filters.ALL

    # Importar handlers
    from bot.command_handlers import (
        backup_command,
        calendar_command,
        gallery_command,
        help_command,
        linkedin_command,
        news_command,
        start_command,
        status_command,
        message_handler_fn,
    )
    from bot.cost_handler import cost_command
    from bot.callback_handlers import linkedin_callback

    # Comandos
    app.add_handler(CommandHandler("start",    start_command,    filters=whitelist))
    app.add_handler(CommandHandler("help",     help_command,     filters=whitelist))
    app.add_handler(CommandHandler("news",     news_command,     filters=whitelist))
    app.add_handler(CommandHandler("calendar", calendar_command, filters=whitelist))
    app.add_handler(CommandHandler("linkedin", linkedin_command, filters=whitelist))
    app.add_handler(CommandHandler("backup",   backup_command,   filters=whitelist))
    app.add_handler(CommandHandler("sync",     backup_command,   filters=whitelist))
    app.add_handler(CommandHandler("gallery",  gallery_command,  filters=whitelist))
    app.add_handler(CommandHandler("status",   status_command,   filters=whitelist))
    app.add_handler(CommandHandler("cost",     cost_command,     filters=whitelist))

    # Mensajes de texto → LangGraph
    app.add_handler(MessageHandler(
        whitelist & filters.TEXT & ~filters.COMMAND,
        message_handler_fn,
    ))

    # Callbacks de botones inline (aprobación LinkedIn)
    app.add_handler(CallbackQueryHandler(
        linkedin_callback,
        pattern=r"^linkedin:",
    ))

    # Handler global de errores — evita el warning "No error handlers registered"
    app.add_error_handler(_error_handler)

    return app


async def _error_handler(update: object, context) -> None:
    """Registra cualquier excepción no capturada y notifica al usuario si es posible."""
    import traceback
    tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    logger.error("Excepción no capturada en handler:\n{}", tb)

    # Intentar notificar al usuario del error
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ha ocurrido un error procesando tu mensaje. "
                "Comprueba los logs o inténtalo de nuevo."
            )
        except Exception:
            pass  # Si falla el reply, no hacer nada
