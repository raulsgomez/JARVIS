"""
ServiceContainer — raíz de inyección de dependencias.

Se construye una sola vez en main.py y se pasa a todos los componentes.
Los agentes NUNCA instancian LLMs ni acceden a globals directamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from cost.tracker import CostTracker
    from cost.llm_wrapper import TrackedLLM


class _LMStudioEmbeddingFunction:
    """
    Función de embedding que llama directamente a LM Studio via httpx.

    Evita los problemas de autenticación del SDK de OpenAI cuando se usa
    con una API key ficticia (como "lm-studio") en un servidor local.
    """

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._name = f"lm-studio-{model}"

    # ChromaDB llama a name() como método
    def name(self) -> str:
        return self._name

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        import httpx

        resp = httpx.post(
            self._url,
            headers=self._headers,
            json={"model": self._model, "input": input},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # La API devuelve los embeddings en orden por "index"
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


@dataclass
class ServiceContainer:
    """
    Contenedor de servicios compartidos.

    Cada agente recibe una instancia de este contenedor en __init__.
    Los LLMs se crean vía factory para tener attribution por agente en cost tracking.
    """

    cost_tracker: CostTracker
    checkpointer: BaseCheckpointSaver
    _lm_studio_base_url: str
    _lm_studio_api_key: str
    _main_model: str
    _router_model: str
    _embedding_model: str
    _cloud_model: str
    _anthropic_api_key: str
    _chromadb_path: str

    def get_main_llm(self, agent_name: str) -> TrackedLLM:
        """LLM local principal (LM Studio) con cost tracking."""
        from cost.llm_wrapper import TrackedLLM
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=self._main_model,
            base_url=self._lm_studio_base_url,
            api_key=self._lm_studio_api_key,
            timeout=120,
            temperature=0.3,
        )
        return TrackedLLM(llm, self.cost_tracker, agent_name)

    def get_router_llm(self, agent_name: str = "router") -> TrackedLLM:
        """LLM ligero para routing/clasificación (más rápido, contexto corto)."""
        from cost.llm_wrapper import TrackedLLM
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=self._router_model,
            base_url=self._lm_studio_base_url,
            api_key=self._lm_studio_api_key,
            timeout=30,
            temperature=0.0,
        )
        return TrackedLLM(llm, self.cost_tracker, agent_name)

    def get_cloud_llm(self, agent_name: str) -> TrackedLLM:
        """LLM cloud (Anthropic) — solo para LinkedIn posts."""
        from cost.llm_wrapper import TrackedLLM
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=self._cloud_model,
            api_key=self._anthropic_api_key,
            max_tokens=2048,
        )
        return TrackedLLM(llm, self.cost_tracker, agent_name)

    def _get_chroma_collection(self, name: str = "jarvis_memory"):
        """ChromaDB con embeddings de LM Studio (nomic-embed-text)."""
        import chromadb

        client = chromadb.PersistentClient(path=self._chromadb_path)
        ef = _LMStudioEmbeddingFunction(
            base_url=self._lm_studio_base_url,
            model=self._embedding_model,
            api_key=self._lm_studio_api_key,
        )
        return client.get_or_create_collection(name, embedding_function=ef)

    async def store_memory(self, user_msg: str, reply: str, agent: str) -> None:
        """Guarda una interacción en ChromaDB con embeddings de LM Studio."""
        import time

        collection = self._get_chroma_collection()
        doc_id = f"{agent}_{int(time.time() * 1000)}"
        collection.add(
            documents=[f"User: {user_msg}\nJARVIS ({agent}): {reply}"],
            ids=[doc_id],
            metadatas=[{"agent": agent, "timestamp": time.time()}],
        )

    async def recall_memories(self, query: str, n_results: int = 3) -> list[str]:
        """Busca memorias relevantes usando embeddings de LM Studio."""
        collection = self._get_chroma_collection()
        if collection.count() == 0:
            return []
        results = collection.query(query_texts=[query], n_results=n_results)
        return results["documents"][0] if results["documents"] else []

    async def check_lm_studio_health(self) -> bool:
        """Verifica que LM Studio esté activo."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._lm_studio_base_url}/models")
                return r.status_code == 200
        except Exception:
            return False


async def build_services() -> ServiceContainer:
    """
    Factory function — llamada una sola vez en main.py.
    Construye e inicializa todos los servicios.
    """
    import aiosqlite
    from config.settings import settings
    from cost.tracker import CostTracker
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    # Cost tracker
    cost_tracker = CostTracker(db_path=str(settings.db_path))
    await cost_tracker.init_db()

    # LangGraph checkpointer — conexión aiosqlite directa (evita context manager)
    conn = await aiosqlite.connect(str(settings.db_path))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    checkpointer = AsyncSqliteSaver(conn)
    # Crear las tablas del checkpointer si no existen (imprescindible para interrupt/resume)
    await checkpointer.setup()

    return ServiceContainer(
        cost_tracker=cost_tracker,
        checkpointer=checkpointer,
        _lm_studio_base_url=settings.lm_studio.base_url,
        _lm_studio_api_key=settings.lm_studio.api_key,
        _main_model=settings.lm_studio.main_model,
        _router_model=settings.lm_studio.router_model,
        _embedding_model=settings.lm_studio.embedding_model,
        _cloud_model=settings.cloud_model,
        _anthropic_api_key=settings.anthropic_api_key,
        _chromadb_path=str(settings.chromadb_path),
    )
