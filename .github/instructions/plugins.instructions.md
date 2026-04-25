---
description: "Use when creating or updating backend plugins. Covers PluginBase, create_plugin(), router exposure, metadata, and the difference between runtime discovery and plugin_registry.yaml documentation."
applyTo: "backend/app/plugins/**"
---

# Plugin Instructions

- Runtime plugin discovery is package-based. The loader scans `backend/app/plugins/` with `pkgutil` and expects a `create_plugin()` factory.
- Implement `PluginBase` from `backend/app/plugins/__init__.py`.
- Required runtime methods are `get_metadata()` and `get_router()`.
- Optional lifecycle hooks are `on_startup()` and `on_shutdown()`.
- Keep plugin routes self-contained and use the same auth dependencies as the rest of the backend.
- Plugins must not import from other plugins. Move shared code into `app.core` or `app.services`.
- `plugin_registry.yaml` is useful documentation, but it is not the runtime registration mechanism in the current codebase.

## Verify

- Lint: `uv run ruff check app/`
- Type-check: `uv run mypy app/ --ignore-missing-imports`
- Tests: `uv run pytest tests/ -v --tb=short`

## Key References

- `backend/app/plugins/__init__.py`
- `backend/app/plugins/aks_insights/__init__.py`
- `backend/app/plugins/keyvault_ops/__init__.py`
- `plugin_registry.yaml`
