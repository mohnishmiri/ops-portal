"""TP15 deterministic topology performance budget certification."""

from __future__ import annotations

import json
import os
import statistics
import time
import tracemalloc
from pathlib import Path
from datetime import UTC, datetime

import pytest

from migration_intake.topology.contracts import serialize_snapshot_document
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import (
    project_v3_snapshot,
    serialize_strict_projection,
)

_ROWS = (10, 100, 1000, 5000)
_P95_SECONDS = 3.0
_PEAK_MIB = 32.0
_AUTHORITY_BYTES = 2 * 1024 * 1024


def _document(count: int) -> dict[str, object]:
    rows = [
        {
            "id": f"R-{index:05}",
            "interface_correlation_id": f"N-{index:05}",
            "interface_app_acronym": f"N-{index:05}",
            "interface_system_location": "AWS",
            "data_traffic_direction": "Inbound",
            "target_protocol": "HTTPS",
            "future_port": "443",
            "origin": "IMPORT",
            "row_version": 1,
        }
        for index in range(count)
    ]
    return {
        "schema_version": "3.0.0",
        "application": {"id": "APP", "name": "App", "acronym": "APP", "identifiers": []},
        "catalog": {
            "id": "CAT",
            "version": "1",
            "source_sha256": "a" * 64,
            "catalog_hash": "b" * 64,
            "compiler_version": "1",
        },
        "intake": {
            "id": "INTAKE",
            "state": "FROZEN",
            "frozen_at": "2026-09-23T00:00:00.000Z",
            "frozen_by": "ACTOR",
            "row_version": 1,
            "content_epoch": 1,
        },
        "answers": [],
        "interface_register": {"interface_epoch": 1, "rows": rows},
        "resources": [],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }


@pytest.mark.parametrize("count", _ROWS)
def test_projection_meets_tp15_budget(count: int) -> None:
    selection = ScopeSelection("APP", "INTAKE", (ContextKey("PROD", "SITE_A"),), "details")
    durations: list[float] = []
    peak = 0
    projection = None
    contract = None
    document = _document(count)
    for _ in range(3):
        tracemalloc.start()
        contract = serialize_snapshot_document(document)
        projection = project_v3_snapshot(
            contract.canonical_json, contract.sha256_hex, selection, (), datetime.now(UTC)
        )
        _, observed_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        started = time.perf_counter()
        contract = serialize_snapshot_document(document)
        projection = project_v3_snapshot(
            contract.canonical_json, contract.sha256_hex, selection, (), datetime.now(UTC)
        )
        durations.append(time.perf_counter() - started)
        tracemalloc.start()
        _ = serialize_strict_projection(projection)
        _, serialization_peak = tracemalloc.get_traced_memory()
        observed_peak = max(observed_peak, serialization_peak)
        tracemalloc.stop()
        peak = max(peak, observed_peak)
    assert contract is not None and projection is not None
    p50 = statistics.median(durations)
    p95 = max(durations)
    projection_bytes = len(serialize_strict_projection(projection).encode())
    receipt = {
        "rows": count,
        "p50_seconds": round(p50, 6),
        "p95_seconds": round(p95, 6),
        "peak_mib": round(peak / 1048576, 3),
        "authority_bytes": len(contract.canonical_json.encode()),
        "projection_bytes": projection_bytes,
        "sql_count": 0,
        "dom_cells": len(projection.nodes) + len(projection.flows),
        "projection_sha256": projection.projection_hash,
    }
    receipt_dir = Path(os.environ.get("TP15_EVIDENCE_DIR", ".pytest_cache/tp15-evidence"))
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / f"performance-{count}.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8"
    )
    assert p95 <= _P95_SECONDS
    assert peak / 1048576 <= _PEAK_MIB
    assert len(contract.canonical_json.encode()) <= _AUTHORITY_BYTES
    assert len(projection.nodes) == count + 1
    assert len(projection.flows) == count
