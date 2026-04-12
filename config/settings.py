"""
Configuración centralizada de JARVIS.

Secrets se leen de macOS Keychain (hardware-backed en Apple Silicon).
Config no-secreta se lee de settings.yaml.
Variables de entorno con prefijo JARVIS_ sobreescriben todo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import keyring
import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_yaml() -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / "settings.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


_yaml = _load_yaml()

# Rutas base calculadas a nivel de módulo (evita problemas con pydantic v2 validators)
_BASE_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BASE_DIR / "data"
_LOGS_DIR = _BASE_DIR / "logs"


class LMStudioSettings(BaseSettings):
    """LM Studio — API compatible con OpenAI en localhost:1234."""
    base_url: str = "http://localhost:1234/v1"
    main_model: str = "qwen/qwen3.5-9b"
    router_model: str = "qwen/qwen3.5-9b"
    embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    api_key: str = "lm-studio"     # LM Studio no valida la key, pero la librería la requiere
    timeout: int = 120


class ScheduleSettings(BaseSettings):
    timezone: str = "Europe/Madrid"
    news_digest_hour: int = 8
    news_digest_minute: int = 0
    linkedin_post_day: str = "tue"
    linkedin_post_hour: int = 10
    backup_hour: int = 2


class NewsSettings(BaseSettings):
    rss_feeds: list[str] = Field(default_factory=lambda: [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    ])
    max_articles_per_feed: int = 5


class WebSettings(BaseSettings):
    """Galería web de fotos."""
    port: int = 8080
    host: str = "0.0.0.0"
    thumbs_dir: str = "~/Pictures/JARVIS-Thumbs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identity ---
    app_name: str = "JARVIS"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # --- Sub-configs (populated from settings.yaml) ---
    lm_studio: LMStudioSettings = Field(default_factory=lambda: LMStudioSettings(
        **_yaml.get("lm_studio", {}),
    ))
    schedule: ScheduleSettings = Field(default_factory=lambda: ScheduleSettings(
        **_yaml.get("schedule", {}),
    ))
    news: NewsSettings = Field(default_factory=lambda: NewsSettings(
        **_yaml.get("news", {}),
    ))
    web: WebSettings = Field(default_factory=lambda: WebSettings(
        **_yaml.get("web", {}),
    ))

    # --- Cloud LLM ---
    cloud_model: str = _yaml.get("cloud", {}).get("model", "claude-haiku-4-5-20251001")

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: list[int] = Field(
        default_factory=lambda: _yaml.get("telegram", {}).get("allowed_user_ids", []),
    )

    # --- API keys (populated from Keychain) ---
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # --- LinkedIn ---
    linkedin_access_token: str = ""
    linkedin_person_id: str = _yaml.get("linkedin", {}).get("person_id", "")

    # --- CalDAV ---
    caldav_url: str = _yaml.get("caldav", {}).get("url", "https://caldav.icloud.com")
    caldav_username: str = _yaml.get("caldav", {}).get("username", "")
    caldav_password: str = ""

    # --- Pricing (USD per 1M tokens) ---
    pricing: dict[str, dict[str, float]] = Field(
        default_factory=lambda: _yaml.get("pricing", {}),
    )

    # --- Paths (con defaults calculados a nivel de módulo) ---
    base_dir: Path = Field(default=_BASE_DIR)
    data_dir: Path = Field(default=_DATA_DIR)
    logs_dir: Path = Field(default=_LOGS_DIR)
    db_path: Path = Field(default=_DATA_DIR / "jarvis.db")
    chromadb_path: Path = Field(default=_DATA_DIR / "chromadb")
    google_credentials_path: Path = Field(default=_DATA_DIR / "google_credentials.json")
    google_token_path: Path = Field(default=_DATA_DIR / "google_token.json")

    # --- Backup ---
    backup_output_dir: str = _yaml.get("backup", {}).get("output_dir", "~/Pictures/JARVIS-Backup")
    backup_days_back: int = _yaml.get("backup", {}).get("days_back", 1)

    # --- Web gallery (personal, fuera de WebSettings para soporte de env vars) ---
    web_tailscale_ip: str = ""   # IP Tailscale del Mac para acceso remoto

    # --- Gallery ---
    gallery_token: str = ""

    @model_validator(mode="after")
    def _init_dirs_and_secrets(self) -> Settings:
        # Crear directorios necesarios
        for d in [self.data_dir, self.logs_dir, self.chromadb_path]:
            d.mkdir(parents=True, exist_ok=True)

        # Pull secrets from macOS Keychain (falls back silently if not set)
        self.telegram_bot_token = self.telegram_bot_token or _keychain("telegram_bot_token")
        self.anthropic_api_key = self.anthropic_api_key or _keychain("anthropic_api_key")
        self.google_api_key = self.google_api_key or _keychain("google_api_key")
        self.linkedin_access_token = self.linkedin_access_token or _keychain("linkedin_access_token")
        self.caldav_password = self.caldav_password or _keychain("caldav_password")
        self.gallery_token = self.gallery_token or _keychain("gallery_token")

        # Crear directorio de thumbnails
        Path(self.web.thumbs_dir).expanduser().mkdir(parents=True, exist_ok=True)

        return self


def _keychain(key: str) -> str:
    """Read a secret from macOS Keychain. Returns '' if not found."""
    try:
        return keyring.get_password("jarvis", key) or ""
    except Exception:
        return ""


settings = Settings()
