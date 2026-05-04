#!/usr/bin/env bash
# bump_version.sh — Bump the project version across all version files.
#
# Usage:
#   ./bump_version.sh [major|minor|patch]   # auto-calculates new version
#   ./bump_version.sh --set 2.3.1           # pin to an explicit version
#
# Files updated:
#   backend/pyproject.toml
#   frontend/package.json
#   frontend/src/App.tsx         (APP_VERSION constant — shown in UI footer)
#   helm/ops-portal/Chart.yaml  (both 'version' and 'appVersion')

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYPROJECT="$SCRIPT_DIR/backend/pyproject.toml"
PACKAGE_JSON="$SCRIPT_DIR/frontend/package.json"
APP_TSX="$SCRIPT_DIR/frontend/src/App.tsx"
CHART_YAML="$SCRIPT_DIR/helm/ops-portal/Chart.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

usage() {
  echo "Usage: $0 [major|minor|patch]"
  echo "       $0 --set <version>"
  echo ""
  echo "  major  Increment the major component (1.2.3 → 2.0.0)"
  echo "  minor  Increment the minor component (1.2.3 → 1.3.0)"
  echo "  patch  Increment the patch component (1.2.3 → 1.2.4)  [default]"
  echo ""
  echo "  --set <version>   Set an explicit semver version (e.g. --set 2.0.0)"
  exit 1
}

# Read the current version from pyproject.toml as the canonical source
current_version() {
  grep -E '^version\s*=' "$PYPROJECT" | head -1 | sed 's/version\s*=\s*"\(.*\)"/\1/'
}

bump_semver() {
  local version="$1"
  local part="$2"
  local major minor patch
  IFS='.' read -r major minor patch <<< "$version"
  case "$part" in
    major) echo "$((major + 1)).0.0" ;;
    minor) echo "${major}.$((minor + 1)).0" ;;
    patch) echo "${major}.${minor}.$((patch + 1))" ;;
    *) echo "Unknown bump part: $part" >&2; exit 1 ;;
  esac
}

validate_semver() {
  if ! [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: '$1' is not a valid semver (expected X.Y.Z)" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

BUMP_PART="patch"
NEW_VERSION=""

case "${1:-patch}" in
  --set)
    [[ -z "${2:-}" ]] && usage
    NEW_VERSION="$2"
    validate_semver "$NEW_VERSION"
    ;;
  major|minor|patch)
    BUMP_PART="${1:-patch}"
    ;;
  --help|-h)
    usage
    ;;
  *)
    echo "ERROR: Unknown argument '$1'" >&2
    usage
    ;;
esac

CURRENT="$(current_version)"
if [[ -z "$CURRENT" ]]; then
  echo "ERROR: Could not read current version from $PYPROJECT" >&2
  exit 1
fi

if [[ -z "$NEW_VERSION" ]]; then
  NEW_VERSION="$(bump_semver "$CURRENT" "$BUMP_PART")"
fi

validate_semver "$NEW_VERSION"

echo "Bumping version: $CURRENT → $NEW_VERSION"
echo ""

# ---------------------------------------------------------------------------
# Update files
# ---------------------------------------------------------------------------

# backend/pyproject.toml
sed -i "s/^version = \"${CURRENT}\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT"
echo "  [updated] backend/pyproject.toml"

# frontend/package.json  (only the top-level "version" field)
# Use a targeted replacement: match the exact value on the version line.
sed -i "s/\"version\": \"${CURRENT}\"/\"version\": \"${NEW_VERSION}\"/" "$PACKAGE_JSON"
echo "  [updated] frontend/package.json"

# frontend/src/App.tsx  (APP_VERSION constant rendered in the UI footer)
sed -i "s/const APP_VERSION = \"${CURRENT}\"/const APP_VERSION = \"${NEW_VERSION}\"/" "$APP_TSX"
echo "  [updated] frontend/src/App.tsx"

# helm/ops-portal/Chart.yaml  (version + appVersion)
sed -i "s/^version: ${CURRENT}$/version: ${NEW_VERSION}/" "$CHART_YAML"
sed -i "s/^appVersion: \"${CURRENT}\"$/appVersion: \"${NEW_VERSION}\"/" "$CHART_YAML"
echo "  [updated] helm/ops-portal/Chart.yaml"

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

echo ""
echo "Verification:"
grep -E '^version\s*=' "$PYPROJECT"  | head -1 | sed 's/^/  pyproject.toml  : /'
grep '"version"' "$PACKAGE_JSON"     | head -1 | sed 's/^/  package.json    : /'
grep 'APP_VERSION' "$APP_TSX"        | head -1 | sed 's/^/  App.tsx         : /'
grep -E '^version:|^appVersion:' "$CHART_YAML" | sed 's/^/  Chart.yaml      : /'

echo ""
echo "Done. New version: $NEW_VERSION"
