#!/bin/bash
# Quick-start backend with uv (development mode with --reload)
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
uv sync --native-tls
uv run --native-tls uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
