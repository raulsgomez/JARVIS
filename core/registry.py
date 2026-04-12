"""
Agent Registry — descubrimiento dinámico de agentes.

Cada agente se registra al ser importado mediante el decorador @register_agent.
El router y el graph leen el registry sin importar agentes directamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from agents.base import BaseAgent


@dataclass(frozen=True)
class AgentMeta:
    """Metadata de un agente registrado."""

    name: str
    description: str  # usado por el router LLM para elegir agente
    cls: Type[BaseAgent]
    intent_examples: tuple[str, ...] = field(default_factory=tuple)
    has_approval_flow: bool = False  # True → graph usa interrupt_before


class AgentRegistry:
    """Registro central de agentes. Singleton a nivel de módulo."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentMeta] = {}

    def register(self, meta: AgentMeta) -> None:
        if meta.name in self._agents:
            raise ValueError(f"Agent '{meta.name}' already registered")
        self._agents[meta.name] = meta

    def get(self, name: str) -> AgentMeta:
        return self._agents[name]

    def all(self) -> list[AgentMeta]:
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def agents_with_approval(self) -> list[AgentMeta]:
        return [m for m in self._agents.values() if m.has_approval_flow]

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents


# Singleton — populated at import time by @register_agent decorators
registry = AgentRegistry()


def register_agent(
    name: str,
    description: str,
    intent_examples: list[str] | None = None,
    has_approval_flow: bool = False,
):
    """
    Decorador de clase. Registra el agente en el registry global al importar.

    Uso:
        @register_agent(
            name="weather",
            description="Responde preguntas sobre el clima",
            intent_examples=["¿Qué tiempo hace?", "¿Lloverá mañana?"],
        )
        class WeatherAgent(BaseAgent): ...
    """

    def decorator(cls):
        registry.register(
            AgentMeta(
                name=name,
                description=description,
                cls=cls,
                intent_examples=tuple(intent_examples or []),
                has_approval_flow=has_approval_flow,
            )
        )
        return cls

    return decorator
