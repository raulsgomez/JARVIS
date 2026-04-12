# JARVIS — Personal AI Assistant

A personal AI assistant running locally on macOS, orchestrated via [LangGraph](https://github.com/langchain-ai/langgraph) and accessible through Telegram. It coordinates specialized agents for calendar management, news digests, LinkedIn posts, iCloud Photos backup, and general conversation — with real-time cost tracking and a photo gallery web interface.

---

## Architecture

```
Telegram ──► Bot handlers
                 │
                 ▼
           LangGraph Graph
           ┌────────────────────────────────────────┐
           │  Router (fast-path regex + LLM fallback)│
           │      │                                  │
           │  ┌───┴────────────────────────────┐     │
           │  │ Agent Registry (auto-discovered)│     │
           │  │  - chat        - calendar       │     │
           │  │  - news        - linkedin       │     │
           │  │  - icloud                       │     │
           │  └─────────────────────────────────┘     │
           │  State: JarvisState (LangGraph checkpt.) │
           └────────────────────────────────────────┘
                 │
         ┌───────┼──────────────┐
         ▼       ▼              ▼
    LM Studio  Anthropic    APScheduler
   (local LLM) Claude       (cron jobs)
                             │
                    ┌────────┴──────────┐
                    ▼                   ▼
             Daily news digest   Weekly LinkedIn post
             Daily photo backup
```

**Key design patterns:**
- **Registry + decorator** — New agents added with `@register_agent`, no graph modifications needed
- **ServiceContainer** — Dependency injection root; passed to all agents
- **TrackedLLM wrapper** — Transparent cost logging on every LLM call
- **Human-in-the-loop** — LinkedIn posts require Telegram approval before publishing
- **Keychain-first secrets** — All credentials stored in macOS Keychain, never in files

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph + LangChain |
| Local LLM | LM Studio (OpenAI-compatible API) |
| Cloud LLM | Anthropic Claude (haiku, for LinkedIn) |
| Telegram bot | python-telegram-bot |
| Calendar | Google Calendar API + CalDAV (Apple Calendar) |
| News | feedparser + trafilatura |
| Photos | osxphotos (macOS Photos Library) |
| Vector memory | ChromaDB + nomic-embed embeddings |
| State persistence | LangGraph + aiosqlite |
| Cost tracking | SQLite |
| Web gallery | aiohttp + Leaflet.js |
| Scheduling | APScheduler |
| Config | Pydantic Settings + PyYAML |
| Secrets | macOS Keychain (`keyring`) |

---

## Requirements

- **macOS** (required for Keychain, osxphotos, and iCloud integration)
- **Python 3.13+**
- **[LM Studio](https://lmstudio.ai)** running locally with models loaded:
  - Main model: `qwen/qwen3.5-9b` (or any instruction-tuned model)
  - Router model: `phi-3.5-mini-instruct` (lightweight)
  - Embedding model: `text-embedding-nomic-embed-text-v1.5`
- A **Telegram bot token** (create one via [@BotFather](https://t.me/BotFather))
- An **Anthropic API key** (optional, only used for LinkedIn posts)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USER/JARVIS.git
cd JARVIS

# 2. Create virtual environment
python3.13 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure (see Configuration section below)
cp settings.example.yaml settings.yaml
cp .env.example .env
```

---

## Configuration

### 1. `settings.yaml` (non-secret config)

Edit `settings.yaml` to match your setup:
- LM Studio model IDs (must match the "Model ID" shown in LM Studio's Local Server tab)
- Schedule timezone and times
- RSS feeds for the news digest
- CalDAV URL and backup paths

### 2. `.env` (personal IDs)

Edit `.env` with your personal identifiers:

```bash
# Your Telegram numeric user ID — get it by messaging @userinfobot on Telegram
JARVIS_TELEGRAM_ALLOWED_USER_IDS=[123456789]

# Your LinkedIn person URN — from GET https://api.linkedin.com/v2/userinfo
JARVIS_LINKEDIN_PERSON_ID=urn:li:person:XXXXXXXXX

# Your Tailscale IP for remote gallery access (optional)
JARVIS_WEB_TAILSCALE_IP=100.x.x.x

# Your iCloud email for Apple Calendar (CalDAV)
JARVIS_CALDAV_USERNAME=you@icloud.com
```

### 3. Secrets (macOS Keychain)

Store all API keys and tokens in the macOS Keychain under the service name `jarvis`:

```bash
python -c "import keyring; keyring.set_password('jarvis', 'telegram_bot_token', 'YOUR_TOKEN')"
python -c "import keyring; keyring.set_password('jarvis', 'anthropic_api_key', 'sk-ant-...')"
python -c "import keyring; keyring.set_password('jarvis', 'google_api_key', 'YOUR_KEY')"
python -c "import keyring; keyring.set_password('jarvis', 'linkedin_access_token', 'YOUR_TOKEN')"
python -c "import keyring; keyring.set_password('jarvis', 'caldav_password', 'YOUR_APP_PASSWORD')"
python -c "import keyring; keyring.set_password('jarvis', 'gallery_token', 'YOUR_TOKEN')"
```

> Alternatively, you can set secrets as `JARVIS_*` env vars in `.env` (see `.env.example`). Keychain takes precedence on macOS.

### 4. Google OAuth credentials

For Google Calendar integration:
1. Create a project in [Google Cloud Console](https://console.cloud.google.com)
2. Enable the **Google Calendar API**
3. Create OAuth 2.0 credentials (Desktop app)
4. Download the credentials JSON and save it as `data/google_credentials.json`
5. On first run, JARVIS will open a browser for OAuth authorization and save the token to `data/google_token.json`

---

## Running

```bash
# Start LM Studio and load your models first, then:
python main.py
```

JARVIS starts:
1. Telegram bot (polling mode)
2. APScheduler (cron jobs)
3. Web photo gallery at `http://localhost:8080`

To run as a macOS background service, see `launchd/com.jarvis.plist`.

---

## Telegram Commands

| Command | Description |
|---|---|
| `/news` | Fetch and summarize today's news digest |
| `/calendar` | Show upcoming calendar events (Google + Apple) |
| `/linkedin` | Generate a LinkedIn post draft (requires approval) |
| `/sync` | Sync iCloud Photos library to local index |
| `/gallery` | Get the web gallery URL |
| `/cost` | Show LLM usage and cost summary |
| `/status` | Show system status (LM Studio, services) |
| `/help` | List all commands |
| _(free text)_ | Chat with the AI assistant |

---

## Adding a New Agent

Agents are auto-discovered — no graph changes needed:

```python
# agents/weather/__init__.py
from agents.base import BaseAgent
from core.registry import register_agent
from core.state import JarvisState
from typing import Any

@register_agent(
    name="weather",
    description="Answers weather questions",
    intent_examples=["What's the weather?", "Will it rain tomorrow?", "Forecast for Madrid"],
)
class WeatherAgent(BaseAgent):
    agent_name = "weather"

    @property
    def system_prompt(self) -> str:
        return "You are a weather assistant. Answer questions about weather concisely."

    async def run(self, state: JarvisState) -> dict[str, Any]:
        llm = self.services.local_llm("weather")
        # ... your implementation
        return {"messages": [...]}
```

The router will automatically detect and route weather-related messages to this agent.

---

## Cost Tracking

Every LLM call is wrapped in `TrackedLLM`, which logs:
- Model name and agent name
- Input/output token counts
- Cost in USD (from pricing table in `settings.yaml`)

Query with `/cost` in Telegram, or directly:

```bash
sqlite3 data/jarvis.db "SELECT agent, model, SUM(cost_usd) FROM llm_cost GROUP BY agent, model;"
```

---

## Web Gallery

A local web server (port 8080) serves your Photos Library metadata:

- `GET /` — Photo gallery with filters and map view
- `GET /api/photos` — Paginated JSON API
- `GET /api/photos/{id}/thumb` — Thumbnail (JPEG)
- `GET /api/photos/{id}/original` — Original file stream
- `GET /api/photos/map` — GPS-tagged photos for Leaflet map

Access is optionally protected by a Bearer token configured via `JARVIS_GALLERY_TOKEN`.

Run `/sync` in Telegram to index your Photos Library before browsing.
