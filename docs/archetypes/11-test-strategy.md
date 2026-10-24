# 11 — Test Strategy & Coverage Gap Analysis: `ops-portal`

## 1. Verification & Quality-Gate Posture

- **Discovered Test / Spec Files:** `25`
- **Total Repository Files:** `558`
- **Primary Test Command:** `npm test`

## 2. Discovered Test Suite Inventory

- `.claude/instructions/tests.instructions.md`
- `.claude/prompts/write-tests.prompt.md`
- `.github/instructions/tests.instructions.md`
- `.github/prompts/write-tests.prompt.md`
- `backend/.pytest-compliance.exit`
- `backend/.pytest-compliance.out`
- `backend/test_endpoints.sh`
- `backend/test_output.txt`
- `backend/tests/__init__.py`
- `backend/tests/access_helpers.py`
- `backend/tests/conftest.py`
- `backend/tests/jks_reader.py`
- `backend/tests/test_access_api.py`
- `backend/tests/test_access_scope.py`
- `backend/tests/test_admin_cors_config.py`
- `backend/tests/test_admin_dashboard_controls.py`
- `backend/tests/test_aks_audit_history.py`
- `backend/tests/test_aks_cronjob_sync.py`
- `backend/tests/test_aks_detail_and_logs.py`
- `backend/tests/test_aks_helm_operations.py`
- `backend/tests/test_aks_helm_releases.py`
- `backend/tests/test_aks_jobs.py`
- `backend/tests/test_aks_nodepools.py`
- `backend/tests/test_aks_performance.py`
- `backend/tests/test_aks_pod_delete.py`

## 3. Module-by-Module Coverage & Gap Matrix

| Module | Source Files | Dedicated Test Files Detected | Coverage Posture & Recommendation |
|---|---|---|---|
| `backend` | 245 | ✅ Yes | Maintain unit + integration assertions on module changes |
| `docs` | 17 | ⚠️ None matched | Add automated regression tests covering active entrypoints in this module |
| `frontend` | 200 | ⚠️ None matched | Add automated regression tests covering active entrypoints in this module |
| `helm` | 15 | ✅ Yes | Maintain unit + integration assertions on module changes |
| `memories` | 19 | ⚠️ None matched | Add automated regression tests covering active entrypoints in this module |
| `root` | 7 | ⚠️ None matched | Add automated regression tests covering active entrypoints in this module |

## 4. Recommended Testing Pyramid for `ops-portal`

1. **Contract / Syntax Validation:** Validate configuration and manifest files (`.github/actions/python-ci/action.yml`) on every commit.
2. **Unit & Component Tests:** Verify domain symbols and error branches cataloged in `07-data-model.md` and `08-error-taxonomy.md`.
3. **Ingress Integration Tests:** Exercise all 30 active ingress paths inventoried in `02-ARCHITECTURE.md`.
