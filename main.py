"""
JARVIS — Entry point.

Un único proceso asyncio que coordina:
  1. ServiceContainer (LLMs, cost tracker, checkpointer, ChromaDB)
  2. Registry de agentes (auto-discovery)
  3. LangGraph (grafo dinámico)
  4. Telegram bot (polling)
  5. APScheduler (cron jobs)
"""

import asyncio
import os
import signal
import sys
from pathlib import Path

# Asegurarse de que el directorio raíz esté en el path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

from config.logging_config import setup_logging
from config.settings import settings

_PID_FILE = Path(__file__).parent / "data" / "jarvis.pid"


def _acquire_pid_lock() -> None:
    """Evita arrancar dos instancias simultáneas."""
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _PID_FILE.exists():
        old_pid = int(_PID_FILE.read_text().strip())
        try:
            os.kill(old_pid, 0)  # comprueba si el proceso existe
            print(f"❌ JARVIS ya está corriendo (PID {old_pid}). Usa: kill {old_pid}")
            sys.exit(1)
        except ProcessLookupError:
            pass  # proceso muerto, el PID file es stale — sobrescribimos
    _PID_FILE.write_text(str(os.getpid()))


def _release_pid_lock() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


async def main() -> None:
    _acquire_pid_lock()
    setup_logging()
    logger.info("Iniciando JARVIS v{} (PID {})", settings.app_version, os.getpid())

    # 1. Construir servicios (DB, LLMs, cost tracker)
    from core.services import build_services
    services = await build_services()
    logger.info("ServiceContainer listo")

    # 2. Pre-flight: verificar LM Studio
    if not await services.check_lm_studio_health():
        logger.warning(
            "⚠️  LM Studio no responde en {}. "
            "Asegúrate de que esté abierto con el servidor local activo.",
            settings.lm_studio.base_url,
        )

    # 3. Auto-discovery de agentes
    import agents  # noqa: F401 — side-effect: popula el registry
    from core.registry import registry
    logger.info("Agentes registrados: {}", registry.names())

    # 4. Construir grafo LangGraph
    from core.graph import build_graph
    graph = build_graph(services)
    logger.info("LangGraph compilado con {} agentes", len(registry))

    # 5. Construir aplicación Telegram
    from bot.telegram_bot import build_application
    app = build_application(services)
    app.bot_data["graph"] = graph

    # 6. Construir scheduler (aún no arrancado)
    from scheduler.jobs import build_scheduler
    scheduler = build_scheduler(graph=graph, bot=app.bot)

    # 6b. Preparar web gallery (aiohttp — mismo event loop)
    from aiohttp import web as aiohttp_web
    from web.app import build_web_app
    from web.photo_index import migrate_db as _migrate_photo_db
    from web.photo_index import setup_db as _setup_photo_db

    await _setup_photo_db(str(settings.db_path))
    await _migrate_photo_db(str(settings.db_path))

    if not settings.gallery_token:
        logger.warning("⚠️  gallery_token no configurado en Keychain — galería sin autenticación")

    _web_app = build_web_app(
        db_path=str(settings.db_path),
        backup_root=settings.backup_output_dir,
        thumbs_dir=settings.web.thumbs_dir,
        token=settings.gallery_token,
    )
    _runner = aiohttp_web.AppRunner(_web_app)
    await _runner.setup()
    _site = aiohttp_web.TCPSite(_runner, host=settings.web.host, port=settings.web.port)
    await _site.start()
    logger.info("📸 Web gallery en http://{}:{}", settings.web.host, settings.web.port)

    # 7. Registrar timestamp de arranque y scheduler en bot_data (usado por /status)
    import time as _time
    app.bot_data["start_time"] = _time.time()
    app.bot_data["scheduler"] = scheduler

    # 8. Arrancar todo en el mismo event loop usando el modo manual de PTB v20+
    #    run_polling() gestiona su propio loop — incompatible con asyncio.run().
    #    La forma correcta es: async with app → updater.start_polling → app.start → wait
    async with app:
        await app.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )
        await app.start()

        scheduler.start()
        logger.info("APScheduler arrancado con {} jobs", len(scheduler.get_jobs()))
        logger.info("Bot de Telegram activo en @jarvis_raulbot. Esperando mensajes...")

        # Mantener el proceso vivo hasta Ctrl+C o señal de sistema
        stop_event = asyncio.Event()

        def _handle_signal():
            logger.info("Señal de parada recibida.")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal)

        await stop_event.wait()

        # Apagado limpio
        logger.info("Apagando JARVIS...")
        scheduler.shutdown(wait=False)
        await _runner.cleanup()
        await app.updater.stop()
        await app.stop()
        _release_pid_lock()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("JARVIS detenido por el usuario.")
    finally:
        _release_pid_lock()
