"""
Web gallery — aiohttp app que sirve las fotos de Photos Library.

Rutas:
  GET /                           → HTML gallery (index.html)
  GET /api/photos                 → JSON paginado (year, month, favorite, is_video, person, album, type)
  GET /api/photos/map             → JSON todas las fotos con GPS (para mapa Leaflet)
  GET /api/photos/people          → JSON lista de personas únicas
  GET /api/photos/albums          → JSON lista de álbumes únicos
  GET /api/photos/{id}/thumb      → JPEG thumbnail 400x400
  GET /api/photos/{id}/original   → stream del archivo original
  GET /api/stats                  → estadísticas del backup

Auth: Bearer token en header Authorization o ?token= query param.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from aiohttp import web
from loguru import logger

from web.photo_index import get_albums, get_people, get_stats, list_photos, list_photos_map


def _auth_middleware(token: str):
    @web.middleware
    async def _middleware(request: web.Request, handler):
        if request.path.startswith("/static"):
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")
        q_token = request.rel_url.query.get("token", "")

        if token and (auth_header == f"Bearer {token}" or q_token == token):
            return await handler(request)

        if not token:
            logger.warning("[gallery] gallery_token no configurado — acceso sin autenticación")
            return await handler(request)

        raise web.HTTPUnauthorized(reason="Token inválido. Accede con ?token=TU_TOKEN")

    return _middleware


def build_web_app(
    db_path: str,
    backup_root: str,
    thumbs_dir: str,
    token: str,
) -> web.Application:
    app = web.Application(middlewares=[_auth_middleware(token)])

    app["db_path"] = db_path
    app["backup_root"] = backup_root
    app["thumbs_dir"] = Path(thumbs_dir).expanduser()

    # Rutas — el orden importa: rutas específicas antes que {id}
    app.router.add_get("/", _gallery_html)
    app.router.add_get("/api/photos", _list_photos)
    app.router.add_get("/api/photos/map", _get_map_photos)
    app.router.add_get("/api/photos/people", _get_people)
    app.router.add_get("/api/photos/albums", _get_albums)
    app.router.add_get("/api/photos/{id}/thumb", _get_thumb)
    app.router.add_get("/api/photos/{id}/original", _get_original)
    app.router.add_get("/api/stats", _get_stats)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.router.add_static("/static", path=str(static_dir), name="static")

    return app


# ── Handlers ────────────────────────────────────────────────────────────────

async def _gallery_html(req: web.Request) -> web.Response:
    index_html = Path(__file__).parent / "static" / "index.html"
    if index_html.exists():
        return web.FileResponse(str(index_html))
    return web.Response(
        text="<h1>JARVIS Gallery</h1><p>index.html not found</p>",
        content_type="text/html",
    )


async def _list_photos(req: web.Request) -> web.Response:
    q = req.rel_url.query

    year_str = q.get("year", "")
    month_str = q.get("month", "")
    year = int(year_str) if year_str.isdigit() else None
    month = int(month_str) if month_str.isdigit() else None
    page = max(1, int(q.get("page", "1") or "1"))
    page_size = min(200, max(1, int(q.get("page_size", "60") or "60")))

    favorite = q.get("favorite", "") == "1"
    is_video_str = q.get("is_video", "")
    is_video = True if is_video_str == "1" else (False if is_video_str == "0" else None)
    person = q.get("person", "") or None
    album = q.get("album", "") or None
    photo_type = q.get("type", "") or None

    result = await list_photos(
        req.app["db_path"],
        year=year, month=month,
        favorite=favorite, is_video=is_video,
        person=person, album=album, photo_type=photo_type,
        page=page, page_size=page_size,
    )
    return web.json_response(result)


async def _get_map_photos(req: web.Request) -> web.Response:
    """Devuelve todas las fotos con GPS para el mapa Leaflet."""
    items = await list_photos_map(req.app["db_path"])
    return web.json_response(items)


async def _get_people(req: web.Request) -> web.Response:
    people = await get_people(req.app["db_path"])
    return web.json_response(people)


async def _get_albums(req: web.Request) -> web.Response:
    albums = await get_albums(req.app["db_path"])
    return web.json_response(albums)


async def _get_thumb(req: web.Request) -> web.Response:
    photo_id = req.match_info["id"]
    thumb_path = req.app["thumbs_dir"] / f"{photo_id}.jpg"
    if not thumb_path.exists():
        raise web.HTTPNotFound(reason=f"Thumbnail no encontrado para id={photo_id}")
    return web.FileResponse(
        str(thumb_path),
        headers={"Content-Type": "image/jpeg", "Cache-Control": "max-age=86400"},
    )


async def _get_original(req: web.Request) -> web.Response:
    """Devuelve el archivo original. ?download=1 fuerza descarga; por defecto inline."""
    photo_id = req.match_info["id"]

    async with aiosqlite.connect(req.app["db_path"]) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT abs_path, mime_type, filename FROM photos WHERE id=?",
            (photo_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise web.HTTPNotFound(reason=f"Foto no encontrada: id={photo_id}")

    path = Path(row["abs_path"])
    if not path.exists():
        raise web.HTTPNotFound(reason=f"Archivo no encontrado en disco: {path}")

    mime = row["mime_type"] or "application/octet-stream"
    filename = row["filename"]
    force_download = req.rel_url.query.get("download", "") == "1"

    disposition = f'attachment; filename="{filename}"' if force_download else "inline"
    return web.FileResponse(
        str(path),
        headers={
            "Content-Type": mime,
            "Content-Disposition": disposition,
        },
    )


async def _get_stats(req: web.Request) -> web.Response:
    stats = await get_stats(req.app["db_path"])
    return web.json_response(stats)
