# 08 — Error Taxonomy & Failure-Mode Catalog: `ops-portal`

## 1. Discovered Error & Exception Catalog

| Error / Exception / Status | Category | Source Location | Handling Context |
|---|---|---|---|
| `Exception` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/access.py:51` | `except Exception as exc:` |
| `ValueError` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:152` | `except ValueError as exc:` |
| `409` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:153` | `raise HTTPException(status_code=409, detail=str(exc)) from exc` |
| `ValueError` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:191` | `except ValueError as exc:` |
| `404` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:192` | `raise HTTPException(status_code=404, detail=str(exc)) from exc` |
| `ValueError` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:229` | `except ValueError as exc:` |
| `404` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:230` | `raise HTTPException(status_code=404, detail=str(exc)) from exc` |
| `ValueError` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:259` | `except ValueError as exc:` |
| `404` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:260` | `raise HTTPException(status_code=404, detail=str(exc)) from exc` |
| `Exception` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:278` | `except Exception as exc:` |
| `502` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:289` | `raise HTTPException(status_code=502, detail=str(exc)) from exc` |
| `ValueError` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/admin.py:415` | `except ValueError as exc:` |
| `400` | Validation / Contract | `backend/app/api/v1/endpoints/admin.py:416` | `raise HTTPException(status_code=400, detail=str(exc)) from exc` |
| `400` | Validation / Contract | `backend/app/api/v1/endpoints/admin.py:418` | `raise HTTPException(status_code=400, detail="At least one valid CORS origin is r` |
| `400` | Validation / Contract | `backend/app/api/v1/endpoints/admin.py:428` | `raise HTTPException(status_code=400, detail="rate_limit_rpm must be an integer."` |
| `400` | Validation / Contract | `backend/app/api/v1/endpoints/admin.py:430` | `raise HTTPException(status_code=400, detail="rate_limit_rpm must be between 10 a` |
| `400` | Validation / Contract | `backend/app/api/v1/endpoints/admin.py:452` | `raise HTTPException(status_code=400, detail="cache_ttl_seconds must be an intege` |
| `400` | Validation / Contract | `backend/app/api/v1/endpoints/admin.py:466` | `raise HTTPException(status_code=400, detail=f"Unknown IANA timezone: {value!r}")` |
| `503` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/aks_dashboard.py:82` | `raise HTTPException(status_code=503, detail="Dashboard session signing is not co` |
| `ValueError` | Runtime / Downstream I/O | `backend/app/api/v1/endpoints/aks_dashboard.py:101` | `except ValueError:` |

## 2. Failure-Mode Analysis & Resilience Posture

| Failure Scenario | Trigger Condition | Observed Code Behavior | Mitigation / Operator Action |
|---|---|---|---|
| Invalid Input / Schema Mismatch | Malformed request payload or missing required parameter | Rejected during entry validation in `.claude/agents/Auth_Buddy.agent.md` | Verify payload against `03-SERVICE-MANIFEST.yaml` and `07-data-model.md` |
| Missing Configuration / Env Binding | Required environment variable or config file absent at startup | Startup or task execution fails fast | Verify all required variables in `01-README.md` |
| Downstream Store / Dependency Unavailable | Network timeout or non-200 response from external dependency | Error propagated to caller / execution log | Follow triage flowchart in `14-runbook.md` |

## 3. Swallowed-Exception & Dead-Letter Audit

- **Silent Catch Audit:** Scanned `558` files across `ops-portal` for unhandled or silently ignored error branches.
- **Retry & Idempotency Posture:** Callers should treat non-GET mutations as non-idempotent unless an explicit idempotency key is supplied.
