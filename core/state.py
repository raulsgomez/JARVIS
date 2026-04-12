"""
Estado compartido de JARVIS (LangGraph TypedDict).

Un único TypedDict fluye por todo el graph y sus sub-grafos.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

AgentName = Literal["chat", "calendar", "news", "linkedin", "icloud"]


class JarvisState(TypedDict, total=False):
    """
    Estado global del grafo JARVIS.

    Campos de mensajes usan `add_messages` (acumulan, no sobreescriben).
    El resto de campos se sobreescriben con el último valor.
    """

    messages: Annotated[list[BaseMessage], add_messages]

    # --- Routing ---
    next_agent: AgentName | None

    # --- Human-in-the-loop (LinkedIn approval) ---
    awaiting_human: bool
    human_feedback: str | None  # "approve" | "reject" | texto libre de edición

    # --- Payloads por agente (solo uno activo a la vez) ---
    linkedin_draft: str | None
    linkedin_approved: bool | None
    calendar_result: dict[str, Any] | None
    news_digest: list[dict[str, Any]] | None
    backup_result: dict[str, Any] | None

    # --- Contexto Telegram (inyectado por el bot, no persistido en checkpoints) ---
    telegram_chat_id: int | None
    telegram_message_id: int | None  # para editar el mensaje de aprobación

    # --- Control de errores ---
    error: str | None
    retry_count: int


def initial_state(
    human_message: str,
    telegram_chat_id: int | None = None,
) -> dict[str, Any]:
    """Crea un estado inicial limpio para una nueva conversación."""
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=human_message)],
        "next_agent": None,
        "awaiting_human": False,
        "human_feedback": None,
        "linkedin_draft": None,
        "linkedin_approved": None,
        "calendar_result": None,
        "news_digest": None,
        "backup_result": None,
        "telegram_chat_id": telegram_chat_id,
        "telegram_message_id": None,
        "error": None,
        "retry_count": 0,
    }
