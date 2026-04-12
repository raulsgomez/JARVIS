"""
Base Agent — clase abstracta para todos los agentes de JARVIS.

Cada agente implementa build_nodes() que devuelve los nodos LangGraph
de su sub-flujo. El graph los conecta automáticamente.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage

if TYPE_CHECKING:
    from core.services import ServiceContainer
    from core.state import JarvisState


class BaseAgent(ABC):
    """
    Clase base para todos los agentes JARVIS.

    Los agentes reciben un ServiceContainer via __init__ (DI).
    Nunca acceden a globals para LLMs, DB, o cost tracker.
    """

    agent_name: str = "base"

    def __init__(self, services: ServiceContainer) -> None:
        from loguru import logger
        self.services = services
        self.llm = services.get_main_llm(agent_name=self.agent_name)
        self.router_llm = services.get_router_llm(agent_name=self.agent_name)
        logger.debug("[AGENT:{}] instancia creada", self.agent_name)

    @abstractmethod
    async def run(self, state: JarvisState) -> dict[str, Any]:
        """
        Procesa el estado y devuelve un dict parcial para actualizar el state.

        Este método es el nodo principal del agente en el graph LangGraph.
        """
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt del agente."""
        ...

    async def recall_context(self, query: str, n_results: int = 3) -> str:
        """Busca memorias relevantes en ChromaDB."""
        from loguru import logger
        memories = await self.services.recall_memories(query, n_results)
        if memories:
            logger.debug("[AGENT:{}] 🧠 {} memorias recuperadas para: '{}'", self.agent_name, len(memories), query[:60])
            return "\n\nContexto relevante de memoria:\n" + "\n---\n".join(memories)
        logger.debug("[AGENT:{}] 🧠 sin memorias previas", self.agent_name)
        return ""

    async def persist_interaction(self, user_msg: str, reply: str) -> None:
        """Guarda la interacción en ChromaDB para recall futuro."""
        from loguru import logger
        try:
            await self.services.store_memory(user_msg, reply, self.agent_name)
            logger.debug("[AGENT:{}] 💾 interacción persistida en ChromaDB", self.agent_name)
        except Exception as exc:
            logger.warning("[AGENT:{}] ⚠️ no se pudo persistir en ChromaDB: {}", self.agent_name, exc)

    def _last_human_message(self, state: JarvisState) -> str:
        """Extrae el último mensaje del usuario."""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                return msg.content
            if isinstance(msg, dict) and msg.get("role") == "human":
                return msg.get("content", "")
        return ""

    def _make_response(self, content: str) -> AIMessage:
        """Crea un AIMessage con el nombre del agente."""
        return AIMessage(content=content, name=self.agent_name)
