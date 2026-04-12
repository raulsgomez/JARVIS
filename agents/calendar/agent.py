"""
Calendar Agent — gestión de Google Calendar y Apple Calendar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.base import BaseAgent
from agents.calendar.tools import (
    create_google_event,
    delete_google_event,
    list_apple_events,
    list_google_events,
)
from core.registry import register_agent

if TYPE_CHECKING:
    from core.state import JarvisState


@register_agent(
    name="calendar",
    description="Consulta, crea o elimina eventos en Google Calendar y Apple Calendar",
    intent_examples=[
        "¿Qué tengo mañana?",
        "Crea una reunión el viernes a las 10",
        "Borra el evento de dentista",
        "¿Tengo algo esta semana?",
    ],
)
class CalendarAgent(BaseAgent):
    agent_name = "calendar"

    @property
    def system_prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()
        today_str = now.strftime("%A %d de %B de %Y, %H:%M")  # ej: "Saturday 12 de April de 2026, 11:35"
        weekday_es = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"][now.weekday()]
        today_es = now.strftime(f"{weekday_es} %d de %B de %Y a las %H:%M")
        return (
            f"Eres el asistente de calendario de JARVIS. "
            f"Hoy es {today_es} (zona horaria: Europe/Madrid). "
            f"La fecha de hoy en ISO es {now.strftime('%Y-%m-%d')}. "
            f"Usa las herramientas disponibles para consultar o modificar eventos. "
            f"Cuando el usuario pregunte por 'hoy', usa days_ahead=1 para obtener eventos de las próximas 24h "
            f"y filtra los que tengan fecha {now.strftime('%Y-%m-%d')}. "
            f"Llama a la herramienta UNA SOLA VEZ y responde con lo que encuentres. "
            f"Si hay eventos, listarlos con hora y título. Si no hay, decirlo claramente. "
            f"Responde siempre en el mismo idioma que el usuario."
        )

    async def run(self, state: JarvisState) -> dict[str, Any]:
        from loguru import logger
        import time

        tools = [
            list_google_events,
            create_google_event,
            delete_google_event,
            list_apple_events,
        ]

        user_msg = self._last_human_message(state)
        logger.info("[CALENDAR] 📅 pregunta: '{}'", user_msg)

        # Construir agente ReAct con las herramientas
        react_agent = create_react_agent(
            model=self._llm_raw(),
            tools=tools,
            prompt=self.system_prompt,
        )

        t0 = time.monotonic()
        result = await react_agent.ainvoke({"messages": state["messages"]})
        elapsed = time.monotonic() - t0

        # Loguear todos los mensajes del ciclo ReAct
        for i, msg in enumerate(result["messages"]):
            msg_type = getattr(msg, "type", "?")
            content = getattr(msg, "content", "")
            tool_calls = getattr(msg, "tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    logger.info("[CALENDAR] 🔧 tool_call: {} args={}", tc.get("name","?"), tc.get("args","{}"))
            elif content and msg_type in ("ai", "tool"):
                preview = (content[:300] + "…") if len(content) > 300 else content
                logger.info("[CALENDAR] msg[{}] type={} | {}", i, msg_type, preview)

        reply = ""
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                reply = msg.content
                break

        logger.info("[CALENDAR] ✅ {:.1f}s | respuesta final: {}", elapsed, (reply[:200] + "…") if len(reply) > 200 else reply)

        await self.persist_interaction(user_msg, reply)

        return {
            "messages": result["messages"],
            "calendar_result": {"status": "completed"},
        }

    def _llm_raw(self):
        """Devuelve el LLM subyacente con tools support (bind_tools lo maneja create_react_agent)."""
        return self.llm._llm  # TrackedLLM delega __getattr__, pero create_react_agent necesita el raw LLM
