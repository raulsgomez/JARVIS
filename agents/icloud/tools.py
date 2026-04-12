"""
Herramientas del iCloud / Photos Agent.

Lee directamente desde Photos Library usando osxphotos (sin exportar archivos).
Cuando el usuario conecta el iPhone por USB e importa en Fotos, las fotos
aparecen automáticamente en la galería web tras ejecutar /sync.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool


@tool
async def sync_photos_library(
    library_path: str | None = None,
) -> dict:
    """
    Sincroniza Photos Library con el índice SQLite y genera thumbnails.

    Lee los metadatos de todas las fotos directamente desde la librería de macOS Photos
    sin exportar ni duplicar archivos. Genera thumbnails JPEG 300x300 para la galería web.

    Args:
        library_path: Path a la librería de Photos (None = usa la librería por defecto del sistema)

    Returns:
        dict con synced, skipped, errors, total y un mensaje resumen
    """
    from config.settings import settings
    from web.photo_index import setup_db, sync_library

    db_path = str(settings.db_path)
    await setup_db(db_path)

    stats = await sync_library(
        db_path=db_path,
        thumbs_dir=settings.web.thumbs_dir,
        library_path=library_path,
    )

    return {
        "synced": stats["synced"],
        "skipped": stats["skipped"],
        "errors": stats["errors"],
        "total": stats["total"],
        "message": (
            f"📚 {stats['total']} fotos en la librería. "
            f"✅ {stats['synced']} nuevas indexadas, "
            f"⏭ {stats['skipped']} ya tenían thumbnail."
        ),
    }
