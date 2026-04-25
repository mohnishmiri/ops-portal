---
description: "Add a new plugin to the Azure Ops Portal plugin system. Use when creating backend/app/plugins packages with PluginBase and create_plugin()."
argument-hint: "Describe the plugin purpose, routes, metadata, and any frontend discovery needs"
agent: "agent"
---

# Add a New Plugin

Create a new plugin for the Azure Ops Portal plugin system.

## Context
- Plugins live in `backend/app/plugins/<plugin_name>/`
- Every plugin must implement the `PluginBase` interface from `backend/app/plugins/`
- Plugins are auto-discovered via `pkgutil` and a `create_plugin()` factory
- `plugin_registry.yaml` is documentation/metadata guidance, not the runtime loader
- Plugins must NOT import from other plugins

## Steps
1. Create a new directory: `backend/app/plugins/{{PLUGIN_NAME}}/`
2. Add `__init__.py` that defines the plugin, any routes, and a `create_plugin() -> PluginBase` factory
3. Implement the `PluginBase` interface:
   - `get_metadata()` returning `PluginMetadata`
   - `get_router()` returning an `APIRouter`
   - Optional `on_startup()` / `on_shutdown()` hooks when needed
4. Expose routes and auth dependencies the same way existing plugins do
5. Optionally update `plugin_registry.yaml` if you want the documentation/examples to mention the new plugin
6. Add unit tests in `backend/tests/test_<plugin_name>_plugin.py`
7. Use `structlog` for logging — no `print()` statements
8. Handle Azure SDK exceptions inside the plugin; do not let them propagate raw

## Variables
- `PLUGIN_NAME`: snake_case name for the new plugin (e.g., `resource_tagging`)
- `DESCRIPTION`: what the plugin does

## Acceptance Criteria
- [ ] Plugin class implements `PluginBase`
- [ ] `create_plugin()` factory is present
- [ ] Runtime discovery works via `pkgutil`
- [ ] Has at least one unit test
- [ ] Passes `ruff check` and `mypy --strict`
- [ ] No imports from other plugins
