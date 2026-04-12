"""
Chat Agent — conversación general con memoria semántica.

El agente más simple: recibe mensajes, responde usando el LLM local,
y guarda interacciones en ChromaDB para recall futuro.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agents.base import BaseAgent
from core.registry import register_agent

if TYPE_CHECKING:
    from core.state import JarvisState


@register_agent(
    name="chat",
    description="Conversación general, preguntas, dudas o peticiones que no encajan en otro agente",
    intent_examples=[
        "¿Qué es LangGraph?",
        "Explícame cómo funciona esto",
        "Hola, ¿cómo estás?",
    ],
)
class ChatAgent(BaseAgent):
    agent_name = "chat"

    @property
    def system_prompt(self) -> str:
        return (
            "Eres JARVIS, un asistente personal inteligente. "
            "Responde de forma concisa y útil en el mismo idioma que el usuario. "
            "Si no sabes algo, dilo claramente."
        )

    async def run(self, state: JarvisState) -> dict[str, Any]:
        user_msg = self._last_human_message(state)

        # Recuperar contexto de memoria semántica
        memory_context = await self.recall_context(user_msg)

        # Construir mensajes con system prompt + historial
        # Los mensajes LangGraph son siempre objetos BaseMessage (no dicts)
        history = []
        for m in state.get("messages", []):
            role = getattr(m, "type", "human")
            # LangChain usa "human"/"ai" — OpenAI espera "user"/"assistant"
            role = {"human": "user", "ai": "assistant"}.get(role, role)
            content = getattr(m, "content", "")
            if content:
                history.append({"role": role, "content": content})

        messages = [
            {"role": "system", "content": self.system_prompt + memory_context},
            *history,
        ]

        response = await self.llm.ainvoke(messages)

        # Persistir interacción en ChromaDB
        await self.persist_interaction(user_msg, response.content)

        return {"messages": [response]}
