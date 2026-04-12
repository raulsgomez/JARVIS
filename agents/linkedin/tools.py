"""
Herramientas del LinkedIn Agent.

Usa la Community Management API oficial de LinkedIn.
Requiere OAuth token con scope w_member_social.
"""

from __future__ import annotations

import httpx
from langchain_core.tools import tool


@tool
async def publish_linkedin_post(
    content: str,
    access_token: str,
    person_id: str,
) -> dict[str, str]:
    """
    Publica un post de texto en LinkedIn usando la Community Management API.

    Args:
        content: Texto del post (máx ~3000 caracteres recomendado)
        access_token: OAuth token con scope w_member_social
        person_id: URN del perfil, ej: "urn:li:person:ABC123"

    Returns:
        dict con 'id' del post y 'url' si está disponible
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    payload = {
        "author": person_id,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=headers,
            json=payload,
        )

    if r.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn API error {r.status_code}: {r.text}")

    post_id = r.headers.get("x-restli-id", "")
    return {
        "id": post_id,
        "url": f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else "",
    }
