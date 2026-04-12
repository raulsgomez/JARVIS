"""
Auto-discovery de agentes.

Importa todos los subpaquetes de agents/ para que los decoradores
@register_agent se ejecuten y pueblen el registry global.

NUNCA hace falta editar este archivo al añadir un agente nuevo.
Basta con crear agents/<nombre>/agent.py con @register_agent.
"""

import importlib
import pkgutil
from pathlib import Path

_agents_dir = Path(__file__).parent

for _mod_info in pkgutil.iter_modules([str(_agents_dir)]):
    if _mod_info.ispkg:
        try:
            importlib.import_module(f"agents.{_mod_info.name}.agent")
        except ModuleNotFoundError:
            # Subpaquete sin agent.py todavía — se ignora
            pass
