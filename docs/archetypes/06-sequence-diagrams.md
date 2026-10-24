# 06 — Sequence Diagrams (One per Ingress Path): `ops-portal`

> Per `orchestrate.agent.md`, each active ingress path in the Step 0.5 Ingress Inventory has its own dedicated `sequenceDiagram`. Unrelated flows are never consolidated.

## Flow 1: `/action` (`REST POST`)

<!-- Source: .claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py:22 -->
- **Source File:** `.claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py:22`
- **Handler / Symbol:** `backend-page-mutation-template::line_22`
- **Kind:** `REST POST` · **Active:** `Y`
- **Summary:** REST POST endpoint `/action` handled in `.claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py:22`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as "backend-page-mutation-template::line_22"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: REST POST /action
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 2: `task:Set up uv` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:47 -->
- **Source File:** `.github/actions/python-ci/action.yml:47`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:47`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Set up uv` in `.github/actions/python-ci/action.yml:47`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:47"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Set up uv
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 3: `task:Cache uv global cache` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:52 -->
- **Source File:** `.github/actions/python-ci/action.yml:52`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:52`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Cache uv global cache` in `.github/actions/python-ci/action.yml:52`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:52"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Cache uv global cache
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 4: `task:Cache virtual environment` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:62 -->
- **Source File:** `.github/actions/python-ci/action.yml:62`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:62`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Cache virtual environment` in `.github/actions/python-ci/action.yml:62`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:62"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Cache virtual environment
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 5: `task:Bridge pip index auth to uv` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:71 -->
- **Source File:** `.github/actions/python-ci/action.yml:71`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:71`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Bridge pip index auth to uv` in `.github/actions/python-ci/action.yml:71`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:71"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Bridge pip index auth to uv
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 6: `task:Sync workspace` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:79 -->
- **Source File:** `.github/actions/python-ci/action.yml:79`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:79`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Sync workspace` in `.github/actions/python-ci/action.yml:79`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:79"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Sync workspace
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 7: `task:Lint (ruff)` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:85 -->
- **Source File:** `.github/actions/python-ci/action.yml:85`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:85`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Lint (ruff)` in `.github/actions/python-ci/action.yml:85`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:85"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Lint (ruff)
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 8: `task:Format check (ruff)` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:91 -->
- **Source File:** `.github/actions/python-ci/action.yml:91`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:91`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Format check (ruff)` in `.github/actions/python-ci/action.yml:91`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:91"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Format check (ruff)
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 9: `task:Type check (mypy)` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:97 -->
- **Source File:** `.github/actions/python-ci/action.yml:97`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:97`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Type check (mypy)` in `.github/actions/python-ci/action.yml:97`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:97"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Type check (mypy)
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 10: `task:Tests with coverage` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:104 -->
- **Source File:** `.github/actions/python-ci/action.yml:104`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:104`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Tests with coverage` in `.github/actions/python-ci/action.yml:104`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:104"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Tests with coverage
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 11: `task:Sanitize ref name for artifact usage` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:120 -->
- **Source File:** `.github/actions/python-ci/action.yml:120`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:120`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Sanitize ref name for artifact usage` in `.github/actions/python-ci/action.yml:120`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:120"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Sanitize ref name for artifact usage
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

## Flow 12: `task:Upload coverage HTML Report` (`Automation Task`)

<!-- Source: .github/actions/python-ci/action.yml:127 -->
- **Source File:** `.github/actions/python-ci/action.yml:127`
- **Handler / Symbol:** `.github/actions/python-ci/action.yml:127`
- **Kind:** `Automation Task` · **Active:** `Y`
- **Summary:** Automation task `Upload coverage HTML Report` in `.github/actions/python-ci/action.yml:127`

```mermaid
sequenceDiagram
participant Caller as "Upstream Caller / Trigger"
participant Ingress as ".github/actions/python-ci/action.yml:127"
participant Domain as "ops-portal Core Logic"
participant Store as ".claude/prompts/add-database-model.prompt.md"
Caller->>Ingress: Automation Task task:Upload coverage HTML Report
Ingress->>Ingress: Validate input & configuration contract
alt Input valid
Ingress->>Domain: Invoke handler (.github/actions/python-ci/action.yml)
Domain->>Store: Read / mutate state or artifact
Store-->>Domain: State / execution result
Domain-->>Ingress: Structured output
Ingress-->>Caller: Success response
else Validation or downstream failure
Ingress-->>Caller: Structured error response
end
```

