"""
TrackedLLM — wrapper sobre cualquier LangChain BaseChatModel con cost tracking.

Hereda de RunnableSerializable para ser compatible con chains LangChain (operador |).
Intercepta ainvoke/invoke, extrae usage_metadata, calcula coste y lo persiste en SQLite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, AsyncIterator, Optional

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.base import RunnableSerializable

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from cost.tracker import CostTracker


class TrackedLLM(RunnableSerializable):
    """
    Wrapper transparente con cost tracking automático.
    Compatible con el operador | de LangChain al heredar de RunnableSerializable.

    Uso:
        llm = TrackedLLM(ChatOpenAI(...), tracker, "linkedin")
        chain = prompt | llm | StrOutputParser()  # funciona
        response = await llm.ainvoke(messages)    # también funciona
    """

    # Campos pydantic (RunnableSerializable es un BaseModel)
    # Usamos nombres con guion bajo para evitar conflictos con pydantic
    class Config:
        arbitrary_types_allowed = True

    _llm: Any
    _tracker: Any
    _agent_name: str
    _model_name: str

    def __init__(self, llm: BaseChatModel, tracker: CostTracker, agent_name: str) -> None:
        # RunnableSerializable.__init__ espera kwargs de pydantic — lo evitamos
        # inicializando directamente los atributos privados
        object.__setattr__(self, "_llm", llm)
        object.__setattr__(self, "_tracker", tracker)
        object.__setattr__(self, "_agent_name", agent_name)
        model_name = (
            getattr(llm, "model_name", None)
            or getattr(llm, "model", None)
            or "unknown"
        )
        object.__setattr__(self, "_model_name", model_name)

    # ── Requerido por RunnableSerializable ──────────────────────────────

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> BaseMessage:
        """Versión síncrona — delega al LLM subyacente con tracking."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # En contexto async ya activo, usar el LLM directamente
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.ainvoke(input, **kwargs))
                    return future.result()
            return loop.run_until_complete(self.ainvoke(input, **kwargs))
        except RuntimeError:
            return asyncio.run(self.ainvoke(input, **kwargs))

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> BaseMessage:
        from loguru import logger
        from cost.tracker import CallRecord

        # ── Log del prompt enviado al modelo ────────────────────────────
        if isinstance(input, list):
            for i, msg in enumerate(input):
                role = msg.get("role", "?") if isinstance(msg, dict) else getattr(msg, "type", "?")
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                preview = (content[:200] + "…") if len(content) > 200 else content
                logger.debug(
                    "[LLM:{}/{}] msg[{}] role={} | {}",
                    self._agent_name, self._model_name, i, role, preview
                )
        else:
            logger.debug("[LLM:{}/{}] input={}", self._agent_name, self._model_name, str(input)[:300])

        try:
            import time
            t0 = time.monotonic()
            response = await self._llm.ainvoke(input, **kwargs)
            elapsed = time.monotonic() - t0

            usage = getattr(response, "usage_metadata", None) or {}
            tokens_in = usage.get("input_tokens", 0)
            tokens_out = usage.get("output_tokens", 0)
            content_out = getattr(response, "content", "")
            preview_out = (content_out[:300] + "…") if len(content_out) > 300 else content_out

            logger.info(
                "[LLM:{}/{}] ✅ {:.1f}s | {}↑ {}↓ tokens | respuesta: {}",
                self._agent_name, self._model_name, elapsed, tokens_in, tokens_out, preview_out
            )

            await self._tracker.log(CallRecord(
                agent_name=self._agent_name,
                model=self._model_name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=self._compute_cost(tokens_in, tokens_out),
                session_id=session_id,
            ))
            return response

        except Exception as exc:
            from cost.tracker import CallRecord
            logger.error("[LLM:{}/{}] ❌ error: {}", self._agent_name, self._model_name, exc)
            await self._tracker.log(CallRecord(
                agent_name=self._agent_name,
                model=self._model_name,
                tokens_in=0, tokens_out=0, cost_usd=0.0,
                session_id=session_id,
                error=str(exc),
            ))
            raise

    # ── Helpers ─────────────────────────────────────────────────────────

    def _compute_cost(self, tokens_in: int, tokens_out: int) -> float:
        from config.settings import settings
        pricing = settings.pricing.get(self._model_name, {})
        if not pricing:
            return 0.0
        return (tokens_in * pricing.get("input", 0.0) + tokens_out * pricing.get("output", 0.0)) / 1_000_000

    def __getattr__(self, item: str) -> Any:
        """Delega bind_tools, with_structured_output, etc. al LLM subyacente."""
        try:
            return object.__getattribute__(self, item)
        except AttributeError:
            return getattr(object.__getattribute__(self, "_llm"), item)

    def __repr__(self) -> str:
        return f"TrackedLLM(model={self._model_name!r}, agent={self._agent_name!r})"
