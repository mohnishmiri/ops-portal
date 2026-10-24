# 05 — Internal Component Diagram: `ops-portal`

## 1. Component Architecture & Wiring (`flowchart TB`)

Every active and inactive ingress path from the Step 0.5 Ingress Inventory is represented below and wired to `ops-portal` internal modules and backing stores:

```mermaid
flowchart TB
    subgraph INGRESS["Ingress & Entrypoints (Step 0.5 Inventory)"]
        ING_0["REST POST: /action (ACTIVE)"]
        ING_1["Automation Task: task:Set up uv (ACTIVE)"]
        ING_2["Automation Task: task:Cache uv global cache (ACTIVE)"]
        ING_3["Automation Task: task:Cache virtual environment (ACTIVE)"]
        ING_4["Automation Task: task:Bridge pip index auth to uv (ACTIVE)"]
        ING_5["Automation Task: task:Sync workspace (ACTIVE)"]
        ING_6["Automation Task: task:Lint (ruff) (ACTIVE)"]
        ING_7["Automation Task: task:Format check (ruff) (ACTIVE)"]
        ING_8["Automation Task: task:Type check (mypy) (ACTIVE)"]
        ING_9["Automation Task: task:Tests with coverage (ACTIVE)"]
        ING_10["Automation Task: task:Sanitize ref name for artifact usage (ACTIVE)"]
        ING_11["Automation Task: task:Upload coverage HTML Report (ACTIVE)"]
    end

    subgraph CORE["ops-portal Internal Modules & Business Logic"]
        M0_BACKEND["Module: backend (245 files)"]
        M1_DOCS["Module: docs (17 files)"]
        M2_FRONTEND["Module: frontend (200 files)"]
        M3_HELM["Module: helm (15 files)"]
        M4_MEMORIES["Module: memories (19 files)"]
        M5_ROOT["Module: root (7 files)"]
    end

    subgraph DATA["Persistence, Schemas & Configuration"]
        CFG_NODE[("Config: .github/actions/python-ci/action.yml")]
        DATA_NODE[("Data/Schema: .claude/prompts/add-database-model.prompt.md")]
    end

    ING_0 --> M0_BACKEND
    ING_1 --> M0_BACKEND
    ING_2 --> M0_BACKEND
    ING_3 --> M0_BACKEND
    ING_4 --> M0_BACKEND
    ING_5 --> M0_BACKEND
    ING_6 --> M0_BACKEND
    ING_7 --> M0_BACKEND
    ING_8 --> M0_BACKEND
    ING_9 --> M0_BACKEND
    ING_10 --> M0_BACKEND
    ING_11 --> M0_BACKEND
    M0_BACKEND --> M1_DOCS
    M1_DOCS --> M2_FRONTEND
    M2_FRONTEND --> M3_HELM
    M3_HELM --> M4_MEMORIES
    M4_MEMORIES --> M5_ROOT
    M5_ROOT --> DATA_NODE
    CFG_NODE -.-> M0_BACKEND
```

## 2. Component-to-Sequence Flow Parity Table

| # | Ingress Path | Node in `05-component-diagram.md` | Sequence Diagram in `06-sequence-diagrams.md` | Status |
|---|---|---|---|---|
| 1 | `/action` | `ING_0` | Flow #1 (`backend-page-mutation-template::line_22`) | ✅ |
| 2 | `task:Set up uv` | `ING_1` | Flow #2 (`.github/actions/python-ci/action.yml:47`) | ✅ |
| 3 | `task:Cache uv global cache` | `ING_2` | Flow #3 (`.github/actions/python-ci/action.yml:52`) | ✅ |
| 4 | `task:Cache virtual environment` | `ING_3` | Flow #4 (`.github/actions/python-ci/action.yml:62`) | ✅ |
| 5 | `task:Bridge pip index auth to uv` | `ING_4` | Flow #5 (`.github/actions/python-ci/action.yml:71`) | ✅ |
| 6 | `task:Sync workspace` | `ING_5` | Flow #6 (`.github/actions/python-ci/action.yml:79`) | ✅ |
| 7 | `task:Lint (ruff)` | `ING_6` | Flow #7 (`.github/actions/python-ci/action.yml:85`) | ✅ |
| 8 | `task:Format check (ruff)` | `ING_7` | Flow #8 (`.github/actions/python-ci/action.yml:91`) | ✅ |
| 9 | `task:Type check (mypy)` | `ING_8` | Flow #9 (`.github/actions/python-ci/action.yml:97`) | ✅ |
| 10 | `task:Tests with coverage` | `ING_9` | Flow #10 (`.github/actions/python-ci/action.yml:104`) | ✅ |
| 11 | `task:Sanitize ref name for artifact usage` | `ING_10` | Flow #11 (`.github/actions/python-ci/action.yml:120`) | ✅ |
| 12 | `task:Upload coverage HTML Report` | `ING_11` | Flow #12 (`.github/actions/python-ci/action.yml:127`) | ✅ |

