"""
Photo metadata index — lee directamente desde Photos Library usando osxphotos.

Responsabilidades:
- DDL: crea la tabla photos y ejecuta migraciones
- sync_library(): sincroniza Photos Library → tabla photos + thumbnails
- list_photos(): consulta paginada con filtros (año, mes, favoritos, personas, álbum, tipo)
- list_photos_map(): fotos con GPS para el mapa
- get_people() / get_albums(): listas para filtros dinámicos
- get_stats(): estadísticas globales
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS photos (
    id          TEXT PRIMARY KEY,
    abs_path    TEXT,
    year        INTEGER NOT NULL DEFAULT 0,
    month       INTEGER NOT NULL DEFAULT 0,
    day         INTEGER NOT NULL DEFAULT 0,
    filename    TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    mime_type   TEXT NOT NULL DEFAULT 'image/jpeg',
    has_thumb   INTEGER NOT NULL DEFAULT 0,
    indexed_at  REAL NOT NULL,
    lat         REAL,
    lon         REAL,
    city        TEXT,
    country     TEXT,
    is_favorite INTEGER DEFAULT 0,
    is_video    INTEGER DEFAULT 0,
    width       INTEGER DEFAULT 0,
    height      INTEGER DEFAULT 0,
    persons     TEXT,
    albums      TEXT,
    photo_type  TEXT
);
CREATE INDEX IF NOT EXISTS photos_date ON photos(year, month, day);
"""

# Columnas añadidas en v2 (migración incremental)
_MIGRATION_COLS = [
    "lat REAL",
    "lon REAL",
    "city TEXT",
    "country TEXT",
    "is_favorite INTEGER DEFAULT 0",
    "is_video INTEGER DEFAULT 0",
    "width INTEGER DEFAULT 0",
    "height INTEGER DEFAULT 0",
    "persons TEXT",
    "albums TEXT",
    "photo_type TEXT",
]


async def migrate_db(db_path: str) -> None:
    """Añade columnas v2 si no existen. Idempotente — seguro llamar siempre."""
    async with aiosqlite.connect(db_path) as db:
        for col in _MIGRATION_COLS:
            try:
                await db.execute(f"ALTER TABLE photos ADD COLUMN {col}")
            except Exception:
                pass  # columna ya existe
        try:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS photos_gps ON photos(lat, lon) "
                "WHERE lat IS NOT NULL"
            )
        except Exception:
            pass
        await db.commit()
    logger.debug("[photo_index] migración v2 completada en {}", db_path)


async def setup_db(db_path: str) -> None:
    """Crea la tabla photos si no existe y ejecuta migraciones."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_TABLE)
        await db.commit()
    await migrate_db(db_path)
    logger.debug("[photo_index] tabla photos lista en {}", db_path)


async def sync_library(
    db_path: str,
    thumbs_dir: str,
    library_path: str | None = None,
) -> dict[str, int]:
    """
    Sincroniza Photos Library con la tabla photos.
    - Fotos nuevas: INSERT + thumbnail
    - Fotos ya indexadas sin metadata v2: UPDATE de nuevas columnas (rápido, sin thumbnail)
    - Fotos completamente al día: skip

    Returns: {"synced": N, "skipped": N, "errors": N, "total": N}
    """
    thumbs = Path(thumbs_dir).expanduser()
    thumbs.mkdir(parents=True, exist_ok=True)

    logger.info("[photo_index] leyendo Photos Library...")
    photos = await asyncio.to_thread(_get_all_photos, library_path)
    logger.info("[photo_index] {} fotos encontradas en la librería", len(photos))

    stats = {"synced": 0, "skipped": 0, "errors": 0, "total": len(photos)}

    async with aiosqlite.connect(db_path) as db:
        for p in photos:
            photo_id = p["uuid"]
            src_path = p.get("path")
            is_video = p.get("is_video", 0)

            # Saltar fotos sin path local
            if not src_path or not Path(src_path).exists():
                stats["skipped"] += 1
                continue

            # Comprobar estado actual en BD
            async with db.execute(
                "SELECT has_thumb, lat FROM photos WHERE id=?", (photo_id,)
            ) as cur:
                row = await cur.fetchone()

            if row and row[0] == 1 and row[1] is not None:
                # Ya completamente indexada (thumbnail + metadata v2) → skip
                stats["skipped"] += 1
                continue

            if row and row[0] == 1 and row[1] is None:
                # Tiene thumbnail pero le falta metadata v2 → solo actualizar columnas
                await db.execute(
                    """UPDATE photos SET
                       lat=?, lon=?, city=?, country=?,
                       is_favorite=?, is_video=?, width=?, height=?,
                       persons=?, albums=?, photo_type=?
                       WHERE id=?""",
                    (
                        p["lat"], p["lon"], p["city"], p["country"],
                        p["is_favorite"], p["is_video"], p["width"], p["height"],
                        p["persons"], p["albums"], p["photo_type"],
                        photo_id,
                    ),
                )
                stats["synced"] += 1

                if stats["synced"] % 500 == 0:
                    await db.commit()
                    logger.info("[photo_index] metadata update: {}/{}", stats["synced"], stats["total"])
                continue

            # Foto nueva o sin thumbnail → INSERT completo
            await db.execute(
                """INSERT INTO photos
                   (id, abs_path, year, month, day, filename, size_bytes, mime_type,
                    has_thumb, indexed_at,
                    lat, lon, city, country, is_favorite, is_video,
                    width, height, persons, albums, photo_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                   abs_path=excluded.abs_path,
                   year=excluded.year, month=excluded.month, day=excluded.day,
                   filename=excluded.filename, size_bytes=excluded.size_bytes,
                   lat=excluded.lat, lon=excluded.lon,
                   city=excluded.city, country=excluded.country,
                   is_favorite=excluded.is_favorite, is_video=excluded.is_video,
                   width=excluded.width, height=excluded.height,
                   persons=excluded.persons, albums=excluded.albums,
                   photo_type=excluded.photo_type""",
                (
                    photo_id, src_path,
                    p["year"], p["month"], p["day"],
                    p["filename"], p["size_bytes"], p["mime_type"],
                    time.time(),
                    p["lat"], p["lon"], p["city"], p["country"],
                    p["is_favorite"], p["is_video"],
                    p["width"], p["height"],
                    p["persons"], p["albums"], p["photo_type"],
                ),
            )

            # Thumbnail (solo para imágenes, no vídeos)
            if not is_video:
                thumb_path = thumbs / f"{photo_id}.jpg"
                has_thumb = thumb_path.exists()
                if not has_thumb:
                    try:
                        await asyncio.to_thread(_make_thumb, src_path, str(thumb_path))
                        has_thumb = True
                    except Exception as exc:
                        logger.warning(
                            "[photo_index] thumbnail fallido para {}: {}", p["filename"], exc
                        )
                        stats["errors"] += 1
                if has_thumb:
                    await db.execute(
                        "UPDATE photos SET has_thumb=1 WHERE id=?", (photo_id,)
                    )

            stats["synced"] += 1

            if stats["synced"] % 500 == 0:
                await db.commit()
                logger.info("[photo_index] progreso: {}/{}", stats["synced"], stats["total"])

        await db.commit()

    logger.info(
        "[photo_index] sync: {} actualizadas, {} skipped, {} errores",
        stats["synced"], stats["skipped"], stats["errors"],
    )
    return stats


def _get_all_photos(library_path: str | None) -> list[dict]:
    """
    Lee todas las fotos de Photos Library via osxphotos incluyendo metadata extendida.
    Síncrono — llamar via asyncio.to_thread().
    """
    import osxphotos

    kwargs = {"library_path": library_path} if library_path else {}
    db = osxphotos.PhotosDB(**kwargs)
    photos = db.photos()

    mime_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "heic": "image/heic", "heif": "image/heic",
        "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "tiff": "image/tiff", "tif": "image/tiff",
        "mov": "video/quicktime", "mp4": "video/mp4", "m4v": "video/mp4",
    }

    result = []
    for p in photos:
        # Path local
        path = p.path or p.path_edited

        # Fecha
        date = p.date
        year = date.year if date else 0
        month = date.month if date else 0
        day = date.day if date else 0

        # MIME y tipo de archivo
        ext = (p.original_filename or "").lower().rsplit(".", 1)[-1]
        mime = mime_map.get(ext, "image/jpeg")
        is_video = 1 if mime.startswith("video/") else 0

        # GPS
        lat = lon = None
        try:
            if p.location and p.location[0] is not None:
                lat, lon = p.location
        except Exception:
            pass

        # Ubicación (reverse geocode — ya está en la BD de Photos, no llama a red)
        city = country = None
        try:
            if p.place:
                if p.place.names.city:
                    city = p.place.names.city[0]
                if p.place.names.country:
                    country = p.place.names.country[0]
        except Exception:
            pass

        # Personas detectadas
        persons = "[]"
        try:
            names = [pe.name for pe in (p.person_info or []) if pe.name]
            persons = json.dumps(names)
        except Exception:
            pass

        # Álbumes
        albums = "[]"
        try:
            titles = [a.title for a in (p.album_info or []) if a.title]
            albums = json.dumps(titles)
        except Exception:
            pass

        # Tipo de foto
        photo_type = ""
        try:
            for t, flag in [
                ("selfie", p.selfie), ("portrait", p.portrait), ("hdr", p.hdr),
                ("panorama", p.panorama), ("screenshot", p.screenshot),
                ("live", p.live_photo), ("slow_mo", p.slow_mo),
                ("time_lapse", p.time_lapse),
            ]:
                if flag:
                    photo_type = t
                    break
        except Exception:
            pass

        # Dimensiones
        width = height = 0
        try:
            width = p.original_width or 0
            height = p.original_height or 0
        except Exception:
            pass

        result.append({
            "uuid": p.uuid,
            "path": path,
            "year": year, "month": month, "day": day,
            "filename": p.original_filename or f"{p.uuid}.jpg",
            "size_bytes": p.original_filesize or 0,
            "mime_type": mime,
            "is_video": is_video,
            "lat": lat, "lon": lon,
            "city": city, "country": country,
            "is_favorite": 1 if (p.favorite or False) else 0,
            "width": width, "height": height,
            "persons": persons, "albums": albums,
            "photo_type": photo_type,
        })

    return result


def _make_thumb(src: str, dst: str) -> None:
    """Genera thumbnail JPEG 400x400. CPU-bound — llamar via asyncio.to_thread()."""
    from PIL import Image

    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    with Image.open(src) as img:
        img.thumbnail((400, 400))
        img = img.convert("RGB")
        img.save(dst, "JPEG", quality=80, optimize=True)


async def list_photos(
    db_path: str,
    year: int | None = None,
    month: int | None = None,
    favorite: bool = False,
    is_video: bool | None = None,
    person: str | None = None,
    album: str | None = None,
    photo_type: str | None = None,
    page: int = 1,
    page_size: int = 60,
) -> dict[str, Any]:
    """Devuelve fotos paginadas con filtros opcionales."""
    conditions: list[str] = []
    params: list[Any] = []

    if year:
        conditions.append("year=?")
        params.append(year)
    if month:
        conditions.append("month=?")
        params.append(month)
    if favorite:
        conditions.append("is_favorite=1")
    if is_video is not None:
        conditions.append("is_video=?")
        params.append(1 if is_video else 0)
    if person:
        conditions.append("persons LIKE ?")
        params.append(f'%"{person}"%')
    if album:
        conditions.append("albums LIKE ?")
        params.append(f'%"{album}"%')
    if photo_type:
        conditions.append("photo_type=?")
        params.append(photo_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(f"SELECT COUNT(*) FROM photos {where}", params) as cur:
            total = (await cur.fetchone())[0]

        offset = (page - 1) * page_size
        rows = await db.execute_fetchall(
            f"SELECT id, filename, year, month, day, size_bytes, mime_type, has_thumb, "
            f"lat, lon, city, country, is_favorite, is_video, width, height, "
            f"persons, albums, photo_type "
            f"FROM photos {where} "
            f"ORDER BY year DESC, month DESC, day DESC, filename "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "items": [dict(r) for r in rows],
    }


async def list_photos_map(db_path: str) -> list[dict[str, Any]]:
    """Devuelve todas las fotos con coordenadas GPS para el mapa."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT id, lat, lon, city, country, year, month, day, is_video, has_thumb "
            "FROM photos WHERE lat IS NOT NULL AND lon IS NOT NULL "
            "ORDER BY year DESC, month DESC, day DESC"
        )
    return [dict(r) for r in rows]


async def get_people(db_path: str) -> list[str]:
    """Devuelve lista de personas únicas (de columna JSON persons)."""
    async with aiosqlite.connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT DISTINCT persons FROM photos WHERE persons IS NOT NULL AND persons != '[]'"
        )
    people: set[str] = set()
    for row in rows:
        try:
            for name in json.loads(row[0]):
                if name:
                    people.add(name)
        except Exception:
            pass
    return sorted(people)


async def get_albums(db_path: str) -> list[str]:
    """Devuelve lista de álbumes únicos (de columna JSON albums)."""
    async with aiosqlite.connect(db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT DISTINCT albums FROM photos WHERE albums IS NOT NULL AND albums != '[]'"
        )
    album_set: set[str] = set()
    for row in rows:
        try:
            for title in json.loads(row[0]):
                if title:
                    album_set.add(title)
        except Exception:
            pass
    return sorted(album_set)


async def get_stats(db_path: str) -> dict[str, Any]:
    """Devuelve estadísticas globales del índice de fotos."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(size_bytes) as total_bytes, "
            "MAX(year * 10000 + month * 100 + day) as last_date, "
            "COUNT(CASE WHEN lat IS NOT NULL THEN 1 END) as with_gps, "
            "COUNT(CASE WHEN is_favorite=1 THEN 1 END) as favorites, "
            "COUNT(CASE WHEN is_video=1 THEN 1 END) as videos "
            "FROM photos"
        ) as cur:
            row = await cur.fetchone()

    last = str(row["last_date"]) if row["last_date"] else None
    if last and len(last) == 8:
        last = f"{last[:4]}-{last[4:6]}-{last[6:]}"

    return {
        "total_photos": row["total"] or 0,
        "total_size_bytes": row["total_bytes"] or 0,
        "last_backup_date": last,
        "with_gps": row["with_gps"] or 0,
        "favorites": row["favorites"] or 0,
        "videos": row["videos"] or 0,
    }
