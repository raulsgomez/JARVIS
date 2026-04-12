"""
RouterNode — clasifica la intención del usuario y elige el agente.

El prompt del router se construye dinámicamente desde el registry,
por lo que nunca hay que editarlo al añadir agentes nuevos.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from langchain_core.prompts import ChatPromptTemplate

if TYPE_CHECKING:
    from core.services import ServiceContainer
    from core.state import JarvisState

# ── Fast-path: keywords → agente sin llamar al LLM ──────────────────────────
# Clave: nombre del agente | Valor: lista de patrones regex (case-insensitive)
_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("calendar", [
        r"\bcalendari[oa]\b", r"\breuni[oó]n\b", r"\bevento\b", r"\bcita\b",
        r"\btengo\s+(mañana|hoy|esta\s+semana)\b", r"\bagenda\b",
        r"\bhorario\b", r"\bprogramar?\b",
    ]),
    ("news", [
        r"\bnoticias?\b", r"\bdigest\b", r"\bnews\b", r"\btitrular(es)?\b",
        r"\bresumen\s+(de\s+)?(hoy|noticias)\b", r"\bactualidad\b",
    ]),
    ("linkedin", [
        r"\blinkedin\b", r"\bpost\b", r"\bpublicar?\b", r"\bpublicaci[oó]n\b",
        r"\bborrador\b", r"\bred\s+profesional\b",
    ]),
    ("icloud", [
        r"\bbackup\b", r"\bfotos?\b", r"\bicloud\b", r"\bexportar?\s+fotos?\b",
        r"\bcopia\s+de\s+seguridad\b",
    ]),
    ("chat", [
        r"\bh[oó]la\b", r"\bbuenos?\s+d[ií]as\b", r"\bbuenas\b",
        r"\bqu[eé]\s+es\b", r"\bexpl[ií]came\b", r"\bc[oó]mo\s+(est[aá]s|funciona)\b",
    ]),
]


def _fast_route(message: str) -> str | None:
    """
    Intenta clasificar el mensaje con reglas de keywords.
    Devuelve el nombre del agente o None si no hay coincidencia clara.
    """
    msg_lower = message.lower()
    for agent_name, patterns in _KEYWORD_RULES:
        for pat in patterns:
            if re.search(pat, msg_lower):
                return agent_name
    return None


def _build_router_prompt() -> str:
    """
    Genera el prompt del router leyendo el registry en tiempo de ejecución.
    Se llama una vez al construir el grafo.
    """
    from core.registry import registry

    agent_lines = []
    for meta in registry.all():
        examples = ""
        if meta.intent_examples:
            examples = " Ejemplos: " + "; ".join(f'"{e}"' for e in meta.intent_examples[:2])
        agent_lines.append(f"- {meta.name}: {meta.description}.{examples}")

    agents_block = "\n".join(agent_lines)

    return f"""Eres el router de JARVIS. Tu única tarea es elegir el agente más adecuado para el mensaje del usuario.

Agentes disponibles:
{agents_block}

Responde ÚNICAMENTE con el nombre del agente (una sola palabra, en minúsculas). Sin explicaciones."""


class RouterNode:
    """Nodo LangGraph que clasifica intenciones y elige el agente destino."""

    def __init__(self, services: ServiceContainer) -> None:
        self._llm = services.get_router_llm(agent_name="router")
        self._prompt_template = ChatPromptTemplate.from_messages([
            ("system", _build_router_prompt()),
            ("human", "{message}"),
        ])

    async def __call__(self, state: JarvisState) -> dict[str, Any]:
        from loguru import logger
        from langchain_core.output_parsers import StrOutputParser
        from core.registry import registry

        # Extraer el último mensaje del usuario
        last_msg = ""
        for msg in reversed(state.get("messages", [])):
            content = getattr(msg, "content", None) or (
                msg.get("content", "") if isinstance(msg, dict) else ""
            )
            role = getattr(msg, "type", None) or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            if role in ("human", "user") and content:
                last_msg = content
                break

        if not last_msg:
            logger.warning("[ROUTER] No se encontró mensaje humano en el estado")
            return {"next_agent": "chat"}

        logger.info("[ROUTER] 📨 mensaje recibido: '{}'", last_msg[:120])

        # 1️⃣  Fast-path: keywords (sin LLM → instantáneo)
        fast = _fast_route(last_msg)
        if fast and fast in registry:
            logger.info("[ROUTER] ⚡ fast-path → {}", fast)
            return {"next_agent": fast}

        # 2️⃣  Fallback LLM (solo si los keywords no son suficientes)
        logger.info("[ROUTER] 🤔 sin keyword match, consultando LLM...")
        try:
            chain = self._prompt_template | self._llm | StrOutputParser()
            chosen = await chain.ainvoke({"message": last_msg})
            chosen_raw = chosen.strip()
            chosen = chosen_raw.lower()

            logger.info("[ROUTER] 🧠 LLM respondió: '{}' → agente: '{}'", chosen_raw, chosen)

            if chosen not in registry:
                logger.warning("[ROUTER] '{}' no es un agente válido, fallback a 'chat'", chosen)
                chosen = "chat"

            return {"next_agent": chosen}

        except Exception as exc:
            logger.warning("[ROUTER] ❌ LLM falló: {} → fallback a 'chat'", exc)
            return {"next_agent": "chat"}
