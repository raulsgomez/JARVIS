"""
Herramientas del News Agent.

- feedparser: RSS feeds (BBC, NYT, Google News, etc.)
- GDELT: noticias globales, gratis, actualización cada 15 min
- trafilatura: extracción del texto completo desde URL
"""

from __future__ import annotations

import asyncio
from typing import Any

import feedparser
import httpx
import trafilatura
from langchain_core.tools import tool


@tool
async def fetch_rss_articles(
    feed_urls: list[str],
    max_per_feed: int = 5,
) -> list[dict[str, str]]:
    """
    Descarga artículos de una lista de feeds RSS.
    Devuelve lista de {title, url, summary, published, source}.
    """
    articles: list[dict[str, str]] = []

    def _parse_feed(url: str) -> list[dict]:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:max_per_feed]:
            results.append({
                "title": entry.get("title", "Sin título"),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", "")[:300],
                "published": entry.get("published", ""),
                "source": feed.feed.get("title", url),
            })
        return results

    # Parsear feeds en paralelo usando threadpool (feedparser es síncrono)
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _parse_feed, url) for url in feed_urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, list):
            articles.extend(result)

    return articles


@tool
async def fetch_gdelt_news(
    query: str,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Consulta GDELT DOC API v2 para noticias recientes sobre un tema.
    Completamente gratuito, actualización cada 15 minutos.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max_results,
        "sort": "DateDesc",
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params=params,
            )
            data = r.json()
        except Exception:
            return []

    articles = []
    for item in data.get("articles", []):
        articles.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("domain", ""),
            "published": item.get("seendate", ""),
            "summary": "",
        })
    return articles


@tool
async def fetch_article_text(url: str) -> str:
    """
    Extrae el texto completo de un artículo desde su URL usando trafilatura.
    Devuelve string vacío si no se puede extraer.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
        return text or ""
    except Exception:
        return ""
