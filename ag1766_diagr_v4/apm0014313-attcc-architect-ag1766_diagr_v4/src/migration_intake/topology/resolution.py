"""
Fact resolution — ported from the validated `_data/spike` design.

This module is a direct port of the POC's ``resolve.py`` conflict-detection,
issue-building, confidence-based selection, and name-composition logic. The
production adapter (``topology/adapter.py``) supplies facts from the database
instead of files; everything downstream of extraction is the same algorithm
as the POC so the same fact shape produces the same resolution outcome.

Design rules:
- Never invent a missing value; unresolved tokens render as ``<name?>``.
- Never silently resolve a same-scope conflict; it becomes an OPEN issue.
- Confidence-based selection only picks a value when exactly one distinct
  value exists at the highest confidence rank for a fact path.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from migration_intake.topology.normalize import normalize_value

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


class ResolutionError(ValueError):
    """Raised when the fact map or resolution configuration is invalid."""


_CONFIDENCE_RANK = {
    "EXISTING": 0,
    "OBSERVED": 1,
    "DERIVED_UNVERIFIED": 2,
    "STATED": 3,
    "SYSTEM": 4,
    "OPERATOR": 5,
}


def normalize_facts(facts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize raw evidence facts in place, preserving raw_value for review."""
    normalized: list[dict[str, Any]] = []
    for source_fact in facts:
        fact = dict(source_fact)
        fact["scope"] = dict(source_fact.get("scope", {}))
        fact["source"] = dict(source_fact.get("source", {}))
        value, inferred_unit = normalize_value(fact["raw_value"], fact.get("data_type", "text"))
        fact["value"] = value
        fact["unit"] = fact.get("unit") or inferred_unit
        normalized.append(fact)
    return normalized


def _scope_key(scope: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(scope.items()))


def _candidate_key(value: Any) -> str:
    if isinstance(value, list):
        return repr(tuple(value))
    return repr(value)


def _facts_by_path(facts: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        grouped[str(fact["path"])].append(dict(fact))
    return grouped


def _same_scope_conflict(candidates: list[Mapping[str, Any]]) -> bool:
    """True when two or more distinct values share the exact same scope."""
    by_scope: dict[tuple[tuple[str, Any], ...], set[str]] = defaultdict(set)
    for candidate in candidates:
        by_scope[_scope_key(candidate.get("scope", {}))].add(_candidate_key(candidate.get("value")))
    return any(len(values) > 1 for values in by_scope.values())


def _condition_matches(
    rule: Mapping[str, Any],
    by_path: Mapping[str, list[dict[str, Any]]],
    interfaces: list[Mapping[str, Any]],
) -> bool:
    paths = rule.get("paths", [])
    candidates = [candidate for path in paths for candidate in by_path.get(path, [])]
    condition = rule["condition"]
    if condition == "missing_path":
        return any(not by_path.get(path) for path in paths)
    if condition == "conflicting_candidates":
        return any(_same_scope_conflict(by_path.get(path, [])) for path in paths)
    if condition == "all_paths_present":
        return all(by_path.get(path) for path in paths)
    if condition == "truthy_with_missing_or_false":
        values = [candidate.get("value") for candidate in candidates]
        return True in values and (False in values or any(not by_path.get(path) for path in paths))
    if condition == "unit_missing":
        return any(candidate.get("unit") is None for candidate in candidates)
    if condition == "declared_ports_not_curated":
        declared = {
            port
            for candidate in candidates
            for port in candidate.get("value", [])
            if isinstance(port, int)
        }
        curated = {
            int(port)
            for interface in interfaces
            for port in re.findall(r"(?<!\d)(\d{1,5})(?!\d)", str(interface.get("port", "")))
            if 0 < int(port) <= 65535
        }
        return bool(declared - curated)
    raise ResolutionError(f"unsupported issue condition {condition}")


_SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def build_issues(
    facts: list[dict[str, Any]],
    interfaces: list[Mapping[str, Any]],
    issue_rules: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate configured issue rules against the extracted facts."""
    by_path = _facts_by_path(facts)
    issues: list[dict[str, Any]] = []
    for rule in issue_rules:
        if not _condition_matches(rule, by_path, interfaces):
            continue
        candidates = [
            candidate for path in rule.get("paths", []) for candidate in by_path.get(path, [])
        ]
        issues.append(
            {
                "id": rule["id"],
                "type": rule["type"],
                "severity": rule["severity"],
                "status": "OPEN",
                "fact_paths": list(rule.get("paths", [])),
                "scope": candidates[0].get("scope", {}) if candidates else {},
                "candidates": candidates,
                "explanation": rule["explanation"],
                "diagram_action": rule["diagram_action"],
                "owner": rule["owner"],
                "requested_action": rule["requested_action"],
                "blocking": bool(rule.get("blocking", False)),
            }
        )
    return sorted(issues, key=lambda item: (_SEVERITY_RANK.get(item["severity"], 9), item["id"]))


def select_values(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the highest-confidence, unambiguous value for each fact path."""
    selected: dict[str, Any] = {}
    by_path = _facts_by_path(facts)
    for path, candidates in by_path.items():
        highest = max(_CONFIDENCE_RANK.get(candidate["confidence"], -1) for candidate in candidates)
        winners = [
            candidate
            for candidate in candidates
            if _CONFIDENCE_RANK.get(candidate["confidence"], -1) == highest
        ]
        values = {_candidate_key(candidate["value"]) for candidate in winners}
        if len(values) == 1:
            selected[path] = winners[0]["value"]
    return selected


def placeholder(name: str) -> str:
    """The visible, never-invented placeholder for a missing token."""
    return f"<{name}?>"


def _name_values(
    *,
    selected: Mapping[str, Any],
    naming_config: Mapping[str, Any],
    site: Mapping[str, Any],
    path_to_token: Mapping[str, str],
) -> dict[str, Any]:
    """Build the base token set directly from selected facts, POC-style."""
    tokens: dict[str, Any] = {}
    for path, token_name in path_to_token.items():
        value = selected.get(path)
        tokens[token_name] = value if value not in (None, "") else placeholder(token_name)

    app_acronym = selected.get("app.acronym")
    tokens.setdefault("app", str(app_acronym) if app_acronym else placeholder("app"))
    tokens.setdefault("app_lower", str(tokens["app"]).lower())

    region_value = selected.get("env.region")
    region_map = naming_config.get("abbrev", {}).get("region", {})
    tokens["region_abbrev"] = str(
        region_map.get(region_value, region_value or placeholder("region"))
    )

    clli = selected.get("site.primary_clli") or site.get("primary_clli")
    dc_map = naming_config.get("abbrev", {}).get("dc", {})
    dc_name_map = naming_config.get("abbrev", {}).get("dc_name", {})
    tokens["dc"] = str(dc_map.get(clli, placeholder("dc")))
    tokens["dc_name"] = str(dc_name_map.get(clli, clli or placeholder("dc_name")))
    return tokens


def compose_names(
    *,
    selected: Mapping[str, Any],
    naming_config: Mapping[str, Any],
    site: Mapping[str, Any],
    path_to_token: Mapping[str, str],
) -> dict[str, str]:
    """Render configured resource-name templates from selected facts."""
    values = _name_values(
        selected=selected, naming_config=naming_config, site=site, path_to_token=path_to_token
    )
    formats = naming_config.get("formats", {})
    composed: dict[str, str] = {}
    for name, template in formats.items():
        try:
            composed[name] = str(template).format(**values)
        except (KeyError, IndexError):
            composed[name] = placeholder(name)
    return composed


def resolve_facts(
    *,
    app_id: str,
    facts: Iterable[Mapping[str, Any]],
    interfaces: Iterable[Mapping[str, Any]] | None = None,
    inputs: Iterable[Mapping[str, Any]] | None = None,
    issue_rules: Iterable[Mapping[str, Any]] | None = None,
    naming_config: Mapping[str, Any] | None = None,
    site: Mapping[str, Any] | None = None,
    path_to_token: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """
    Production equivalent of the POC's ``resolve_evidence``.

    Normalizes facts, evaluates issue rules, selects the highest-confidence
    unambiguous value per path, composes any configured resource names, and
    returns the same resolved shape the POC produces: facts, selected,
    names, tokens, interfaces, inputs, and issues.
    """
    normalized = normalize_facts(facts)
    resolved_issues = build_issues(normalized, list(interfaces or []), issue_rules or [])
    selected = select_values(normalized)
    names = compose_names(
        selected=selected,
        naming_config=naming_config or {},
        site=site or {},
        path_to_token=path_to_token or {},
    )
    tokens = _name_values(
        selected=selected,
        naming_config=naming_config or {},
        site=site or {},
        path_to_token=path_to_token or {},
    )
    tokens.update(names)
    return {
        "app_id": app_id,
        "facts": normalized,
        "selected": selected,
        "names": names,
        "tokens": tokens,
        "interfaces": list(interfaces or []),
        "inputs": list(inputs or []),
        "issues": resolved_issues,
    }
