"""
Handlers de comandos Telegram.

Cada comando invoca el grafo LangGraph con el agente correspondiente
o ejecuta acciones directas (status, backup).
"""

from __future__ import annotations

import uuid

from telegram import Update
from telegram.ext import ContextTypes

from core.state import initial_state


def _graph(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data["graph"]


def _services(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data["services"]


def _thread_id(update: Update, prefix: str = "user") -> str:
    """Thread ID estable por usuario para conversaciones persistentes."""
    return f"{prefix}_{update.effective_user.id}"


_HELP_TEXT = (
    "🤖 *JARVIS — Comandos disponibles*\n\n"
    "📰 *Noticias*\n"
    "• /news — resumen de las noticias del día\n\n"
    "📅 *Calendario*\n"
    "• /calendar — ver qué tienes esta semana\n"
    "• /calendar añade reunión mañana a las 10 — crear evento\n\n"
    "💼 *LinkedIn*\n"
    "• /linkedin — genera un post sobre IA y productividad\n"
    "• /linkedin inteligencia artificial en medicina — tema concreto\n"
    "  _→ te manda el borrador con botones_ ✅ _Publicar_ ❌ _Descartar_ ✏️ _Editar_\n\n"
    "📸 *Galería de fotos*\n"
    "• /sync — indexa las fotos nuevas de Photos Library\n"
    "• /gallery — obtén la URL de la galería web\n\n"
    "💸 *Costes*\n"
    "• /cost — gasto en IA de hoy y del mes\n\n"
    "⚙️ *Sistema*\n"
    "• /status — estado de LM Studio y agentes\n"
    "• /help — este mensaje\n\n"
    "💬 *Chat libre*\n"
    "Escríbeme cualquier cosa y te respondo con el agente adecuado\\.\n"
    "Ejemplos: _\"¿Tengo algo el viernes?\"_, _\"Resúmeme las noticias de hoy\"_, _\"Hola\"_"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Bienvenido a *JARVIS*, tu asistente personal\\.\n\n"
        + _HELP_TEXT,
        parse_mode="MarkdownV2",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP_TEXT, parse_mode="MarkdownV2")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📰 Recopilando noticias...")
    state = initial_state("Dame el resumen de noticias de hoy", update.effective_chat.id)
    state["next_agent"] = "news"

    config = {"configurable": {"thread_id": f"news_{uuid.uuid4().hex[:8]}"}}
    result = await _graph(context).ainvoke(state, config=config)

    digest = result.get("news_digest", [])
    if digest:
        lines = ["📰 *Resumen de noticias*\n"]
        for item in digest[:10]:
            lines.append(f"• [{item.get('title', '?')}]({item.get('url', '')})")
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    else:
        # El agente puede haber puesto el resumen en messages
        for msg in reversed(result.get("messages", [])):
            content = getattr(msg, "content", "")
            if content:
                await update.message.reply_text(content)
                break


async def calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = " ".join(context.args) if context.args else "¿Qué tengo esta semana?"
    state = initial_state(user_text, update.effective_chat.id)
    state["next_agent"] = "calendar"

    config = {"configurable": {"thread_id": _thread_id(update, "calendar")}}
    result = await _graph(context).ainvoke(state, config=config)

    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", "")
        if content and getattr(msg, "type", "") == "ai":
            await update.message.reply_text(content)
            break


async def linkedin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia el flujo de generación + aprobación de post LinkedIn."""
    from loguru import logger
    await update.message.reply_text("✍️ Generando borrador de LinkedIn...")

    topic = " ".join(context.args) if context.args else "tendencias en IA y productividad"
    thread_id = f"linkedin_{uuid.uuid4().hex[:8]}"
    state = initial_state(f"Crea un post de LinkedIn sobre: {topic}", update.effective_chat.id)
    state["next_agent"] = "linkedin"

    config = {"configurable": {"thread_id": thread_id}}
    result = await _graph(context).ainvoke(state, config=config)

    logger.debug("[linkedin_command] result keys: {}", list(result.keys()))
    logger.debug("[linkedin_command] __interrupt__: {}", result.get("__interrupt__"))

    # Cuando interrupt() se ejecuta, LangGraph suspende el nodo antes del return.
    # El draft queda en result["__interrupt__"][0].value, no en result["linkedin_draft"].
    interrupts = result.get("__interrupt__", [])
    if interrupts:
        draft = interrupts[0].value.get("draft", "") if isinstance(interrupts[0].value, dict) else str(interrupts[0].value)
        logger.info("[linkedin_command] graph suspendido, draft recibido ({} chars)", len(draft))
        # Guardar thread_id en bot_data para que el callback handler pueda reanudar
        context.bot_data.setdefault("linkedin_threads", {})[thread_id] = {
            "chat_id": update.effective_chat.id,
            "draft": draft,
        }
        await _send_linkedin_approval(update, context, draft, thread_id)
    elif result.get("awaiting_human") and result.get("linkedin_draft"):
        # Fallback por si el estado sí se escribió
        await _send_linkedin_approval(update, context, result["linkedin_draft"], thread_id)
    else:
        logger.warning("[linkedin_command] no se detectó interrupt ni draft en el resultado")


async def _send_linkedin_approval(update, context, draft: str, thread_id: str) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Publicar", callback_data=f"linkedin:approve:{thread_id}"),
            InlineKeyboardButton("❌ Descartar", callback_data=f"linkedin:reject:{thread_id}"),
        ],
        [InlineKeyboardButton("✏️ Editar (responde con tu feedback)", callback_data=f"linkedin:edit:{thread_id}")],
    ])
    await update.message.reply_text(
        f"📝 *Borrador de LinkedIn:*\n\n{draft}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sincroniza Photos Library con la galería web (antes llamado backup)."""
    await update.message.reply_text(
        "📸 Sincronizando Photos Library con la galería...\n"
        "_(Esto puede tardar unos minutos la primera vez)_",
        parse_mode="Markdown",
    )
    state = initial_state("Sincroniza las fotos", update.effective_chat.id)
    state["next_agent"] = "icloud"

    config = {"configurable": {"thread_id": f"sync_{uuid.uuid4().hex[:8]}"}}
    result = await _graph(context).ainvoke(state, config=config)

    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", "")
        if content and getattr(msg, "name", "") == "icloud":
            await update.message.reply_text(content)
            return

    await update.message.reply_text("✅ Sincronización completada.")


def _fmt_uptime(seconds: float) -> str:
    """Convierte segundos en texto legible: '2d 3h 12m'."""
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes = s // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _fmt_ago(seconds: float) -> str:
    """'hace X'"""
    s = int(seconds)
    if s < 60:
        return "hace menos de 1m"
    if s < 3600:
        return f"hace {s // 60}m"
    if s < 86400:
        return f"hace {s // 3600}h {(s % 3600) // 60}m"
    return f"hace {s // 86400}d"


async def _get_system_info() -> dict:
    """Recoge métricas del sistema vía psutil (en thread pool para no bloquear)."""
    import asyncio
    import psutil
    import time

    def _collect():
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_pct": cpu,
            "ram_used_gb": mem.used / 1e9,
            "ram_total_gb": mem.total / 1e9,
            "ram_pct": mem.percent,
            "disk_free_gb": disk.free / 1e9,
            "disk_total_gb": disk.total / 1e9,
            "disk_pct": disk.percent,
            "sys_uptime_s": time.time() - psutil.boot_time(),
        }

    return await asyncio.to_thread(_collect)


async def _get_power_watts() -> dict:
    """Lee consumo actual del sistema vía ioreg (Apple Silicon, sin sudo)."""
    import asyncio
    import re

    def _read_ioreg():
        import subprocess
        result = {"system_w": None, "adapter_w": None, "plugged_in": None, "battery_pct": None}
        try:
            out = subprocess.check_output(
                ["ioreg", "-rn", "AppleSmartBattery"],
                timeout=3, text=True, stderr=subprocess.DEVNULL,
            )
            # Consumo del sistema (mW → W)
            m = re.search(r'"SystemLoad"\s*=\s*(\d+)', out)
            if m:
                result["system_w"] = int(m.group(1)) / 1000

            # Potencia del adaptador (W)
            m = re.search(r'"Watts"\s*=\s*(\d+)', out)
            if m:
                result["adapter_w"] = int(m.group(1))

            # ¿Enchufado?
            m = re.search(r'"ExternalConnected"\s*=\s*(\w+)', out)
            if m:
                result["plugged_in"] = m.group(1).lower() == "yes"

            # % batería
            m = re.search(r'"CurrentCapacity"\s*=\s*(\d+)', out)
            cap = int(m.group(1)) if m else None
            m = re.search(r'"MaxCapacity"\s*=\s*(\d+)', out)
            maxc = int(m.group(1)) if m else None
            if cap and maxc:
                result["battery_pct"] = round(cap / maxc * 100)
        except Exception:
            pass
        return result

    return await asyncio.to_thread(_read_ioreg)


async def _get_photo_stats(db_path: str) -> dict:
    """Total de fotos y timestamp del último sync."""
    import aiosqlite
    import time

    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT COUNT(*), COUNT(CASE WHEN lat IS NOT NULL THEN 1 END), MAX(indexed_at) FROM photos"
            ) as cur:
                row = await cur.fetchone()
        return {
            "total": row[0] or 0,
            "with_gps": row[1] or 0,
            "last_sync_ago": time.time() - row[2] if row[2] else None,
        }
    except Exception:
        return {"total": 0, "with_gps": 0, "last_sync_ago": None}


async def _get_errors_today(logs_dir) -> tuple[int, list[str]]:
    """Lee jarvis.log y extrae líneas ERROR de las últimas 24h."""
    import asyncio
    from datetime import datetime, timedelta
    from pathlib import Path

    log_file = Path(logs_dir) / "jarvis.log"
    if not log_file.exists():
        return 0, []

    cutoff = datetime.now() - timedelta(hours=24)
    errors = []

    def _read():
        lines = []
        try:
            with open(log_file, "r", errors="replace") as f:
                for line in f:
                    if " | ERROR" in line or " | CRITICAL" in line:
                        # Extraer timestamp y mensaje
                        parts = line.strip().split(" | ", 3)
                        if len(parts) >= 4:
                            try:
                                ts = datetime.strptime(parts[0][:19], "%Y-%m-%d %H:%M:%S")
                                if ts >= cutoff:
                                    # Truncar mensaje largo
                                    msg = parts[3][:80]
                                    time_str = parts[0][11:16]
                                    lines.append(f"[{time_str}] {msg}")
                            except ValueError:
                                pass
        except Exception:
            pass
        return lines

    errors = await asyncio.to_thread(_read)
    return len(errors), errors[-3:]  # máximo 3 últimos


async def _get_lm_model(base_url: str, api_key: str) -> str:
    """Obtiene el modelo actualmente cargado en LM Studio."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            data = r.json()
            models = data.get("data", [])
            if models:
                return models[0].get("id", "?")
    except Exception:
        pass
    return "—"


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import asyncio
    import time

    from config.settings import settings
    from core.registry import registry

    services = _services(context)

    # Recopilar todo en paralelo
    sys_info, power, cost, lm_ok, photo_stats, (err_count, err_lines), lm_model = (
        await asyncio.gather(
            _get_system_info(),
            _get_power_watts(),
            services.cost_tracker.summary(),
            services.check_lm_studio_health(),
            _get_photo_stats(str(settings.db_path)),
            _get_errors_today(settings.logs_dir),
            _get_lm_model(settings.lm_studio.base_url, settings.lm_studio.api_key),
        )
    )

    # Uptime JARVIS vs Mac
    start_time = context.bot_data.get("start_time", time.time())
    jarvis_up = _fmt_uptime(time.time() - start_time)
    mac_up = _fmt_uptime(sys_info["sys_uptime_s"])

    # Próximos jobs — con descripción legible
    scheduler = context.bot_data.get("scheduler")
    job_lines = []
    _JOB_LABELS = {
        "daily_news":      ("📰", "Noticias diarias"),
        "weekly_linkedin": ("💼", "Post LinkedIn"),
        "daily_backup":    ("📸", "Sync fotos"),
    }
    if scheduler:
        for job in scheduler.get_jobs():
            if job.next_run_time:
                icon, label = _JOB_LABELS.get(job.id, ("⏰", job.id))
                t = job.next_run_time.strftime("%a %d/%m %H:%M")
                job_lines.append(f"  {icon} {label} — {t}")

    # LM Studio
    lm_status = "🟢 online" if lm_ok else "🔴 offline"
    lm_line = f"  Modelo: `{lm_model}`" if lm_ok and lm_model != "—" else ""

    # Galería
    photo_line = f"  {photo_stats['total']:,} fotos | {photo_stats['with_gps']:,} con GPS"
    if photo_stats["last_sync_ago"] is not None:
        photo_line += f"\n  Último sync: {_fmt_ago(photo_stats['last_sync_ago'])}"

    # Agentes
    agents_list = ", ".join(f"`{n}`" for n in registry.names())

    # Costes
    cost_line = f"  Hoy: `${cost['today_usd']:.4f}` | Mes: `${cost['month_usd']:.4f}`"

    # Energía
    power_parts = []
    if power.get("system_w") is not None:
        power_parts.append(f"Sistema: `{power['system_w']:.1f} W`")
    if power.get("plugged_in") is not None:
        plug_icon = "🔌" if power["plugged_in"] else "🔋"
        if power.get("battery_pct") is not None and not power["plugged_in"]:
            power_parts.append(f"{plug_icon} batería: `{power['battery_pct']}%`")
        elif power["plugged_in"]:
            adapter_str = f" (adaptador `{power['adapter_w']} W`)" if power.get("adapter_w") else ""
            power_parts.append(f"{plug_icon} enchufado{adapter_str}")
    power_line = "  " + " | ".join(power_parts) if power_parts else ""

    # Disco — nota sobre espacio purgeable
    disk_free = sys_info["disk_free_gb"]
    disk_total = sys_info["disk_total_gb"]
    disk_pct = sys_info["disk_pct"]
    disk_line = (
        f"  Disco: `{disk_free:.0f} GB` libres de `{disk_total:.0f} GB` "
        f"(`{disk_pct:.0f}%` usado)"
    )

    # Errores
    err_section = f"⚠️ *Errores hoy:* {err_count}"
    if err_lines:
        err_section += "\n" + "\n".join(f"  · {e}" for e in err_lines)

    # Jobs
    jobs_section = ""
    if job_lines:
        jobs_section = "⏰ *Próximos jobs*\n" + "\n".join(job_lines) + "\n\n"

    msg = (
        f"⚙️ *JARVIS Status*\n\n"
        f"🤖 *Proceso*\n"
        f"  JARVIS activo: `{jarvis_up}` | Mac sin reiniciar: `{mac_up}`\n"
        f"  Agentes: {agents_list}\n\n"
        f"💻 *Máquina*\n"
        f"  CPU: `{sys_info['cpu_pct']:.0f}%` | "
        f"RAM: `{sys_info['ram_used_gb']:.1f}/{sys_info['ram_total_gb']:.0f} GB` "
        f"(`{sys_info['ram_pct']:.0f}%`)\n"
        f"{disk_line}\n"
        f"{power_line + chr(10) if power_line else ''}"
        f"\n"
        f"🧠 *LM Studio:* {lm_status}\n"
        f"{lm_line + chr(10) if lm_line else ''}"
        f"\n"
        f"💸 *Costes IA*\n"
        f"{cost_line}\n\n"
        f"📸 *Galería*\n"
        f"{photo_line}\n\n"
        f"{jobs_section}"
        f"{err_section}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")


async def gallery_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Devuelve la URL de la galería de fotos con el token incluido."""
    import socket
    from config.settings import settings

    token = settings.gallery_token
    port = settings.web.port

    # Usar Tailscale IP si está configurada (acceso remoto desde cualquier sitio)
    # Si no, caer a mDNS (.local) para red local
    tailscale = settings.web_tailscale_ip
    host = tailscale if tailscale else (socket.gethostname().removesuffix(".local") + ".local")
    url = f"http://{host}:{port}/?token={token}" if token else f"http://{host}:{port}/"

    await update.message.reply_text(
        f"📸 *Galería de fotos*\n\n"
        f"`{url}`\n\n"
        f"_(válida en la misma red WiFi)_",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def message_handler_fn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para mensajes de texto libres — pasan por el router LangGraph."""
    user_text = update.message.text
    chat_id = update.effective_chat.id

    state = initial_state(user_text, chat_id)
    config = {"configurable": {"thread_id": _thread_id(update)}}

    result = await _graph(context).ainvoke(state, config=config)

    # Si el graph se suspendió esperando aprobación humana (LinkedIn via interrupt)
    interrupts = result.get("__interrupt__", [])
    if interrupts:
        thread_id = config["configurable"]["thread_id"]
        draft = interrupts[0].value.get("draft", "") if isinstance(interrupts[0].value, dict) else str(interrupts[0].value)
        context.bot_data.setdefault("linkedin_threads", {})[thread_id] = {
            "chat_id": update.effective_chat.id,
            "draft": draft,
        }
        await _send_linkedin_approval(update, context, draft, thread_id)
        return

    # Respuesta normal: último mensaje de AI
    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", "")
        msg_type = getattr(msg, "type", "")
        if content and msg_type == "ai":
            await update.message.reply_text(content)
            return
