"""
Plugin System — Extensible module loading architecture.

Allows new capabilities (AKS insights, Key Vault ops, etc.) to be
added by implementing PluginBase and registering via plugin_registry.yaml.
"""

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from fastapi import APIRouter, FastAPI

logger = structlog.get_logger(__name__)


@dataclass
class PluginMetadata:
    """Plugin descriptor."""

    name: str
    version: str
    description: str
    author: str = "Platform Engineering"
    enabled: bool = True
    required_roles: list[str] = field(default_factory=lambda: ["read"])
    dashboard_widgets: list[dict] = field(default_factory=list)


class PluginBase(ABC):
    """Abstract base class for all plugins."""

    @abstractmethod
    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        ...

    @abstractmethod
    def get_router(self) -> APIRouter:
        """Return FastAPI router with plugin endpoints."""
        ...

    async def on_startup(self) -> None:
        """Called during application startup."""
        return

    async def on_shutdown(self) -> None:
        """Called during application shutdown."""
        return


class PluginRegistry:
    """Central plugin registry — discovers, loads, and manages plugins."""

    def __init__(self) -> None:
        self.plugins: dict[str, PluginBase] = {}

    async def discover_and_register(self, app: FastAPI) -> None:
        """Auto-discover plugins in the plugins directory."""
        plugins_dir = Path(__file__).parent
        package_name = __name__.rsplit(".", 1)[0] + ".plugins"

        for _finder, module_name, is_pkg in pkgutil.iter_modules([str(plugins_dir)]):
            if not is_pkg or module_name.startswith("_"):
                continue

            try:
                module = importlib.import_module(f"{package_name}.{module_name}")
                if hasattr(module, "create_plugin"):
                    plugin: PluginBase = module.create_plugin()
                    metadata = plugin.get_metadata()

                    if not metadata.enabled:
                        logger.info("plugin_disabled", name=metadata.name)
                        continue

                    self.plugins[metadata.name] = plugin

                    # Register plugin routes
                    router = plugin.get_router()
                    app.include_router(
                        router,
                        prefix=f"/api/v1/plugins/{module_name}",
                        tags=[f"plugin:{metadata.name}"],
                    )

                    await plugin.on_startup()
                    logger.info(
                        "plugin_registered",
                        name=metadata.name,
                        version=metadata.version,
                    )

            except Exception as e:
                logger.error("plugin_load_failed", module=module_name, error=str(e))

    def get_registry_info(self) -> list[dict]:
        """Return metadata for all registered plugins (for frontend discovery)."""
        return [
            {
                "name": p.get_metadata().name,
                "version": p.get_metadata().version,
                "description": p.get_metadata().description,
                "enabled": p.get_metadata().enabled,
                "widgets": p.get_metadata().dashboard_widgets,
            }
            for p in self.plugins.values()
        ]


plugin_registry = PluginRegistry()
