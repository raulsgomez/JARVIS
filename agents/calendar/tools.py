"""
Herramientas del Calendar Agent.

- Google Calendar API (OAuth2)
- Apple Calendar via CalDAV
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.tools import tool


# ──────────────────────────────────────────────
# Google Calendar
# ──────────────────────────────────────────────

def _get_google_service():
    """Construye el servicio de Google Calendar con refresh automático."""
    from pathlib import Path

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as gcal_build

    from config.settings import settings

    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    creds = None

    if settings.google_token_path.exists():
        creds = Credentials.from_authorized_user_file(str(settings.google_token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.google_credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        settings.google_token_path.write_text(creds.to_json())

    return gcal_build("calendar", "v3", credentials=creds)


@tool
def list_google_events(days_ahead: int = 7, calendar_id: str = "primary") -> list[dict]:
    """Lista los próximos eventos de Google Calendar."""
    from loguru import logger
    logger.info("[TOOL:list_google_events] days_ahead={}, calendar_id={}", days_ahead, calendar_id)
    try:
        service = _get_google_service()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()

        result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        ).execute()

        events = []
        for e in result.get("items", []):
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            events.append({
                "id": e["id"],
                "title": e.get("summary", "(Sin título)"),
                "start": start,
                "end": e["end"].get("dateTime", e["end"].get("date", "")),
                "location": e.get("location", ""),
                "description": e.get("description", ""),
            })
        logger.info("[TOOL:list_google_events] ✅ {} eventos encontrados", len(events))
        for ev in events:
            logger.debug("[TOOL:list_google_events]   → {} @ {}", ev["title"], ev["start"])
        return events
    except Exception as exc:
        logger.error("[TOOL:list_google_events] ❌ error: {}", exc)
        raise


@tool
def create_google_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> dict:
    """
    Crea un evento en Google Calendar.
    start_datetime y end_datetime en formato ISO 8601, ej: '2025-06-15T10:00:00+02:00'
    """
    service = _get_google_service()
    event_body = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start_datetime},
        "end": {"dateTime": end_datetime},
    }
    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return {"id": created["id"], "link": created.get("htmlLink", "")}


@tool
def delete_google_event(event_id: str, calendar_id: str = "primary") -> bool:
    """Elimina un evento de Google Calendar por su ID."""
    service = _get_google_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return True


# ──────────────────────────────────────────────
# Apple Calendar (CalDAV)
# ──────────────────────────────────────────────

def _get_caldav_calendar():
    import caldav
    from config.settings import settings

    client = caldav.DAVClient(
        url=settings.caldav_url,
        username=settings.caldav_username,
        password=settings.caldav_password,
    )
    principal = client.principal()
    calendars = principal.calendars()
    return calendars[0] if calendars else None


@tool
def list_apple_events(days_ahead: int = 7) -> list[dict]:
    """Lista próximos eventos de Apple Calendar via CalDAV."""
    from datetime import timezone

    cal = _get_caldav_calendar()
    if not cal:
        return []

    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days_ahead)

    events = []
    for event in cal.date_search(start=start, end=end):
        vevent = event.vobject_instance.vevent
        events.append({
            "title": str(vevent.summary.value),
            "start": str(vevent.dtstart.value),
            "end": str(vevent.dtend.value) if hasattr(vevent, "dtend") else "",
        })
    return events


def init_google_auth() -> None:
    """
    Inicializa el token de Google Calendar (requiere navegador la primera vez).
    Ejecutar una sola vez:
        python -c "from agents.calendar.tools import init_google_auth; init_google_auth()"
    """
    _get_google_service()
    print("Google Calendar autenticado correctamente.")
