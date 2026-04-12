"""
Photos Agent — sincroniza Photos Library con la galería web de JARVIS.

Flujo:
  1. Lee metadatos de Photos Library via osxphotos (sin exportar)
  2. Inserta/actualiza filas en la tabla photos de jarvis.db
  3. Genera thumbnails JPEG para las fotos nuevas
  4. La galería web sirve los thumbnails y los originales en tiempo real

El usuario conecta el iPhone por USB → importa en Fotos → ejecuta /sync en Telegram
→ las fotos nuevas aparecen en la galería web.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agents.base import BaseAgent
from agents.icloud.tools import sync_photos_library
from core.registry import register_agent

if TYPE_CHECKING:
    from core.state import JarvisState


@register_agent(
    name="icloud",
    description="Sincroniza Photos Library con la galería web para acceder a las fotos desde cualquier sitio",
    intent_examples=[
        "Sincroniza las fotos",
        "Actualiza la galería de fotos",
        "Indexa las fotos nuevas",
        "Sync fotos",
    ],
)
class ICloudAgent(BaseAgent):
    agent_name = "icloud"

    @property
    def system_prompt(self) -> str:
        return "Eres el agente de fotos de JARVIS. Tu tarea es sincronizar Photos Library con la galería web."

    async def run(self, state: JarvisState) -> dict[str, Any]:
        from loguru import logger

        logger.info("[icloud] iniciando sincronización con Photos Library...")

        result = await sync_photos_library.ainvoke({})

        msg = (
            f"✅ Galería actualizada\n"
            f"📸 {result['total']} fotos en la librería\n"
            f"🆕 {result['synced']} nuevas indexadas\n"
            f"⏭ {result['skipped']} ya estaban\n"
            f"❌ {result['errors']} errores de thumbnail"
        ) if result.get("total", 0) > 0 else (
            "⚠️ No se encontraron fotos en Photos Library. "
            "Asegúrate de que la app Fotos esté cerrada durante la sincronización."
        )

        return {
            "messages": [self._make_response(msg)],
            "backup_result": result,
        }
