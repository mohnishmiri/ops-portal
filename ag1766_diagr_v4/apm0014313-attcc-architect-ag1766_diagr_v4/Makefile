.PHONY: install lint lint-all typecheck typecheck-all test verify preflight check

PYTHON := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,$(if $(wildcard .venv/bin/python),.venv/bin/python,python))

HTTP_PROXY ?= http://cso.proxy.att.com:8080
HTTPS_PROXY ?= http://cso.proxy.att.com:8080
export HTTP_PROXY HTTPS_PROXY

install:
	$(PYTHON) -m pip install -e ".[dev]"

CHANGED_PYTHON_CMD = powershell -NoProfile -ExecutionPolicy Bypass -Command '$$files = @(git diff --name-only --diff-filter=ACMR HEAD -- src tests | Where-Object { $$_ -like "*.py" }); if ($$files.Count -gt 0) { & "$(PYTHON)" -m ruff check $$files } else { Write-Host "No changed Python files to lint." }'
CHANGED_APP_PYTHON_CMD = powershell -NoProfile -ExecutionPolicy Bypass -Command '$$files = @(git diff --name-only --diff-filter=ACMR HEAD -- src/migration_intake | Where-Object { $$_ -like "*.py" }); if ($$files.Count -gt 0) { & "$(PYTHON)" -m mypy --follow-imports=silent $$files } else { Write-Host "No changed application Python files to type-check." }'

lint:
	$(CHANGED_PYTHON_CMD)

lint-all:
	$(PYTHON) -m ruff check src/

typecheck:
	$(CHANGED_APP_PYTHON_CMD)

typecheck-all:
	$(PYTHON) -m mypy src/migration_intake

test:
	$(PYTHON) -m pytest tests --ignore=tests/browser

verify: install lint typecheck test

preflight: verify

check: verify
