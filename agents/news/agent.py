"""
News Agent — recopila y resume noticias desde RSS y GDELT.

Flujo:
  1. Descarga artículos de los RSS configurados en settings.yaml
  2. Opcionalmente enriquece con GDELT para temas específicos
  3. Resume con el LLM local
  4. Devuelve la lista de artículos + resumen en los mensajes
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agents.base import BaseAgent
from agents.news.tools import fetch_article_text, fetch_gdelt_news, fetch_rss_articles
from core.registry import register_agent

if TYPE_CHECKING:
    from core.state import JarvisState


@register_agent(
    name="news",
    description="Busca y resume las últimas noticias del día desde RSS y fuentes globales",
    intent_examples=[
        "¿Qué ha pasado hoy?",
        "Dame las noticias de hoy",
        "Resumen de noticias",
        "¿Hay algo importante en las noticias?",
    ],
)
class NewsAgent(BaseAgent):
    agent_name = "news"

    @property
    def system_prompt(self) -> str:
        return (
            "Eres el agente de noticias de JARVIS. "
            "Se te proporcionará una lista de titulares y resúmenes de noticias recientes. "
            "Crea un resumen ejecutivo en español, agrupando por tema si es posible. "
            "Sé conciso: 3-5 puntos clave máximo. "
            "Indica la fuente de cada noticia."
        )

    async def run(self, state: JarvisState) -> dict[str, Any]:
        from config.settings import settings

        # 1. Descargar artículos de RSS configurados
        articles = await fetch_rss_articles.ainvoke({
            "feed_urls": settings.news.rss_feeds,
            "max_per_feed": settings.news.max_articles_per_feed,
        })

        # 2. Construir contexto para el LLM
        if not articles:
            return {
                "messages": [self._make_response("No se pudieron obtener noticias en este momento.")],
                "news_digest": [],
            }

        articles_text = "\n\n".join(
            f"[{a['source']}] {a['title']}\n{a['summary']}"
            for a in articles[:15]
        )

        # 3. Resumir con LLM local
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Aquí están los artículos de hoy:\n\n{articles_text}"},
        ]

        response = await self.llm.ainvoke(messages)

        return {
            "messages": [response],
            "news_digest": articles,
        }
