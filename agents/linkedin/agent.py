"""
LinkedIn Agent — genera posts y los publica con aprobación humana.

Flujo con human-in-the-loop:
  1. generate_draft: cloud LLM genera el borrador
  2. El graph se suspende (interrupt_before="linkedin_await_approval")
  3. El bot de Telegram envía el borrador con botones inline
  4. El usuario aprueba/rechaza/edita
  5. El graph reanuda con Command(resume=...) y publica o descarta

El agente usa el LLM cloud (Claude Haiku) para generar el post,
ya que la calidad del contenido público requiere un modelo más capaz.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

from agents.base import BaseAgent
from core.registry import register_agent

if TYPE_CHECKING:
    from core.state import JarvisState


@register_agent(
    name="linkedin",
    description="Genera y publica posts profesionales en LinkedIn, con aprobación previa del usuario",
    intent_examples=[
        "Escribe un post de LinkedIn",
        "Crea contenido para LinkedIn sobre IA",
        "Publica algo en LinkedIn",
        "Genera un post profesional",
    ],
    has_approval_flow=True,
)
class LinkedInAgent(BaseAgent):
    agent_name = "linkedin"

    @property
    def system_prompt(self) -> str:
        return (
            "Eres un experto en marketing de contenidos para LinkedIn. "
            "Crea posts profesionales, auténticos y con buen engagement. "
            "El post debe:\n"
            "- Empezar con un hook que enganche en las primeras líneas\n"
            "- Tener entre 150-300 palabras\n"
            "- Incluir 3-5 hashtags relevantes al final\n"
            "- Ser en el mismo idioma que la petición del usuario\n"
            "- Sonar personal y auténtico, no corporativo\n"
            "Devuelve SOLO el texto del post, sin explicaciones."
        )

    async def run(self, state: JarvisState) -> dict[str, Any]:
        user_msg = self._last_human_message(state)

        # Usar LLM cloud si hay API key; si no, usar el LLM local
        from config.settings import settings
        if settings.anthropic_api_key:
            cloud_llm = self.services.get_cloud_llm(agent_name=self.agent_name)
        else:
            from loguru import logger
            logger.warning("LinkedIn: anthropic_api_key no configurada, usando LLM local")
            cloud_llm = self.llm

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ]

        # Si hay feedback previo de edición, incorporarlo
        feedback = state.get("human_feedback")
        if feedback and feedback not in ("approve", "reject"):
            messages.append({
                "role": "user",
                "content": f"El usuario quiere estos cambios en el borrador anterior:\n{feedback}",
            })

        response = await cloud_llm.ainvoke(messages)
        draft = response.content.strip()

        # Suspender el graph aquí — el bot enviará el draft a Telegram
        # interrupt() persiste el estado y devuelve el control al caller
        human_decision = interrupt({
            "draft": draft,
            "prompt": "Revisa el borrador de LinkedIn y decide si publicarlo.",
        })

        # El graph reanuda aquí con la decisión del usuario
        if human_decision == "approve":
            return await self._publish(draft, state)
        elif human_decision == "reject":
            return {
                "messages": [self._make_response("Post descartado.")],
                "linkedin_draft": None,
                "linkedin_approved": False,
                "awaiting_human": False,
                "human_feedback": None,
            }
        else:
            # Feedback de edición → volver a generar (re-entrará a run con el feedback)
            return {
                "messages": [self._make_response(f"Revisando con tu feedback: {human_decision}")],
                "linkedin_draft": draft,
                "awaiting_human": False,
                "human_feedback": human_decision,
            }

    async def _publish(self, draft: str, state: JarvisState) -> dict[str, Any]:
        from config.settings import settings
        from agents.linkedin.tools import publish_linkedin_post

        try:
            result = await publish_linkedin_post.ainvoke({
                "content": draft,
                "access_token": settings.linkedin_access_token,
                "person_id": settings.linkedin_person_id,
            })
            msg = f"✅ Post publicado en LinkedIn.\n🔗 {result.get('url', '')}"
        except Exception as e:
            msg = f"❌ Error al publicar: {e}"

        return {
            "messages": [self._make_response(msg)],
            "linkedin_draft": draft,
            "linkedin_approved": True,
            "awaiting_human": False,
            "human_feedback": None,
        }
