"""
Graph principal de JARVIS.

El graph se construye dinámicamente leyendo el registry de agentes.
Añadir un agente nuevo NO requiere modificar este archivo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from core.registry import registry
from core.router import RouterNode
from core.state import JarvisState

if TYPE_CHECKING:
    from core.services import ServiceContainer


def build_graph(services: ServiceContainer):
    """
    Construye y compila el grafo principal de JARVIS.

    Estructura:
        router → [agent_1 | agent_2 | ... | agent_N] → END

    Los nodos con has_approval_flow=True añaden interrupt_before
    en su nodo de aprobación (definido en el propio agente).
    """
    g = StateGraph(JarvisState)

    # --- Nodo router ---
    router_node = RouterNode(services)
    g.add_node("router", router_node)
    g.set_entry_point("router")

    # --- Nodos de agentes (descubiertos del registry) ---
    for meta in registry.all():
        agent_instance = meta.cls(services)
        g.add_node(meta.name, agent_instance.run)

    # --- Edges condicionales: router → agente elegido ---
    agent_map = {meta.name: meta.name for meta in registry.all()}
    g.add_conditional_edges("router", lambda s: s["next_agent"], agent_map)

    # --- Todos los agentes terminan en END ---
    for meta in registry.all():
        g.add_edge(meta.name, END)

    # --- Compilar con checkpointing ---
    # El human-in-the-loop del LinkedIn agent usa interrupt() directamente
    # dentro de su run(), no necesita interrupt_before en el compile.
    return g.compile(checkpointer=services.checkpointer)
