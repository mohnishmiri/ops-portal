"""
Topology data adapter Ã¢â‚¬â€ extracts typed facts from the database for topology
generation, then resolves them with the ported POC resolution logic.

This module replaces the POC's file readers (``_data/spike/src/extract.py``)
with a database reader. Every fact it emits has the same shape the POC
extraction produces (``path``, ``scope``, ``raw_value``, ``data_type``,
``unit``, ``source``, ``confidence``), so everything downstream Ã¢â‚¬â€ the
ported ``topology/resolution.py`` normalize/select/build_issues/compose_names
pipeline and the ported ``topology/fill.py`` diagram filler Ã¢â‚¬â€ runs the same
algorithm whether facts came from files (POC) or a database (production).

Design rules:
- Reads from canonical answers and application data.
- Maps question codes to fact paths; never invents a missing value.
- One documented scope simplification: production currently stores a single
  current answer per question per intake (no per-environment answer
  variants), so environment-dependent facts use an empty scope rather than
  the POC's ``{lifecycle, environment}`` scope. The same-scope conflict
  engine is still wired and will detect real conflicts once multiple scoped
  candidates for one path exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from migration_intake.persistence.models import (
    AnswerInstance,
    AnswerRevision,
    Application,
    ApplicationIdentifier,
    CatalogQuestion,
    Intake,
)
from migration_intake.topology.resolution import placeholder, resolve_facts

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_FACT_MAP_PATH = _CONFIG_DIR / "fact_map.json"
_NAMING_CONFIG_PATH = _CONFIG_DIR / "naming.json"


@dataclass
class TopologyToken:
    """A token for diagram rendering."""

    name: str
    value: str | None
    source: str | None = None  # Where the value came from
    question_code: str | None = None


@dataclass
class TopologyData:
    """Data extracted and resolved for topology generation."""

    app_id: str
    app_name: str
    app_acronym: str | None = None
    correlation_id: str | None = None

    tokens: dict[str, str] = field(default_factory=dict)
    token_details: list[TopologyToken] = field(default_factory=list)
    missing_tokens: list[str] = field(default_factory=list)
    # Full resolved-fact record (facts/selected/names/issues) from the ported
    # POC resolution pipeline; the service layer builds report issues from
    # ``issues`` instead of re-deriving them from ``missing_tokens`` alone.
    issues: list[dict[str, Any]] = field(default_factory=list)


# Question code -> (fact path, data type). Mirrors the POC's fact-map.yaml
# "facts:" section, adapted to the codes this catalog can supply.
FACT_REGISTRY: dict[str, tuple[str, str]] = {
    "APP_NAME": ("app.name", "text"),
    "APP_ACRONYM": ("app.acronym", "acronym"),
    "CORRELATION_ID": ("app.correlation_id", "identifier"),
    "MOTS_ID": ("app.mots_id", "identifier"),
    "TARGET_ENVIRONMENT": ("env.name", "text"),
    "TARGET_REGION": ("env.region", "region"),
    "AWS_REGION": ("env.region", "region"),
    "VPC_CIDR": ("network.vpc_cidr", "cidr"),
    "SUBNET_CIDR": ("network.subnet_cidr", "cidr"),
    "OUTPOST_CIDR": ("network.outpost_cidr", "cidr"),
    "DB_ENGINE": ("db.engine", "text"),
    "DB_ENGINE_VERSION": ("db.engine.version", "version"),
    "DB_INSTANCE_TYPE": ("db.instance_type", "text"),
    "DB_STORAGE_SIZE": ("db.storage_size", "text"),
    "EC2_INSTANCE_TYPE": ("compute.ec2_instance_type", "text"),
    "EC2_COUNT": ("compute.ec2_count", "text"),
    "EBS_SIZE": ("storage.ebs_size", "text"),
    "EBS_TYPE": ("storage.ebs_type", "text"),
    "ALB_NAME": ("lb.alb_name", "text"),
    "NLB_NAME": ("lb.nlb_name", "text"),
}

# Identifier type -> (fact path, data type).
IDENTIFIER_REGISTRY: dict[str, tuple[str, str]] = {
    "CORRELATION": ("app.correlation_id", "identifier"),
    "ACRONYM": ("app.acronym", "acronym"),
    "MOTS": ("app.mots_id", "identifier"),
}

# Fact path -> legacy diagram token name, for slot_bindings.json templates
# and backward-compatible TopologyData.tokens keys.
PATH_TO_TOKEN: dict[str, str] = {
    "app.name": "app_name",
    "app.acronym": "app_acronym",
    "app.correlation_id": "correlation_id",
    "app.mots_id": "mots_id",
    "env.name": "environment",
    "env.region": "region",
    "network.vpc_cidr": "vpc_cidr",
    "network.subnet_cidr": "subnet_cidr",
    "network.outpost_cidr": "outpost_cidr",
    "db.engine": "db_engine",
    "db.engine.version": "db_version",
    "db.instance_type": "db_instance_type",
    "db.storage_size": "db_storage_size",
    "compute.ec2_instance_type": "ec2_instance_type",
    "compute.ec2_count": "ec2_count",
    "storage.ebs_size": "ebs_size",
    "storage.ebs_type": "ebs_type",
    "lb.alb_name": "alb_name",
    "lb.nlb_name": "nlb_name",
}

# Backward-compatible alias: some callers historically imported this name.
QUESTION_TO_TOKEN_MAP = {code: PATH_TO_TOKEN[path] for code, (path, _) in FACT_REGISTRY.items()}


def _load_fact_map(path: Path) -> list[dict[str, Any]]:
    """Load issue rules from the versioned JSON config, or [] if unusable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return list(raw.get("issues", []))
    except (OSError, json.JSONDecodeError):
        return []


def _load_naming_config(path: Path) -> dict[str, Any]:
    """Load the naming/abbreviation config, or {} if unusable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {"abbrev": raw.get("abbrev", {}), "formats": raw.get("formats", {})}
    except (OSError, json.JSONDecodeError):
        return {"abbrev": {}, "formats": {}}


def extract_topology_facts(session: Session, intake_id: str) -> dict[str, Any]:
    """
    Extract raw, typed facts from the database for an intake.

    Returns the POC-shaped extraction package: ``{app_id, facts, interfaces,
    inputs}``. Facts are raw (unnormalized); normalization and selection
    happen in ``topology/resolution.py``.
    """
    intake_row = session.execute(
        select(Intake, Application)
        .join(Application, Application.id == Intake.application_id)
        .where(Intake.id == intake_id)
    ).first()

    if intake_row is None:
        raise ValueError(f"Intake {intake_id} not found")

    application = intake_row[1]

    identifiers = session.execute(
        select(ApplicationIdentifier).where(ApplicationIdentifier.application_id == application.id)
    ).scalars().all()

    facts: list[dict[str, Any]] = [
        {
            "path": "app.name",
            "scope": {},
            "raw_value": str(application.display_name),
            "data_type": "text",
            "unit": None,
            "source": {"file": "application", "locator": "display_name"},
            "confidence": "SYSTEM",
        }
    ]

    for ident in identifiers:
        ident_type = str(ident.identifier_type).upper()
        registry_entry = IDENTIFIER_REGISTRY.get(ident_type)
        if registry_entry is None:
            continue
        path, data_type = registry_entry
        facts.append(
            {
                "path": path,
                "scope": {},
                "raw_value": str(ident.raw_value),
                "data_type": data_type,
                "unit": None,
                "source": {"file": "application_identifier", "locator": ident_type},
                "confidence": "SYSTEM",
            }
        )

    answers_query = (
        select(AnswerInstance, AnswerRevision, CatalogQuestion)
        .join(AnswerRevision, AnswerRevision.id == AnswerInstance.current_rev_id)
        .join(CatalogQuestion, CatalogQuestion.id == AnswerInstance.question_id)
        .where(AnswerInstance.intake_id == intake_id)
    )
    answer_rows = session.execute(answers_query).all()

    for row in answer_rows:
        revision = row[1]
        question = row[2]
        question_code = str(question.question_code).upper()

        registry_entry = FACT_REGISTRY.get(question_code)
        if registry_entry is None:
            continue
        path, data_type = registry_entry

        raw_value: str | None = None
        if getattr(revision, "value_text", None):
            raw_value = str(revision.value_text)
        elif getattr(revision, "value_json", None):
            json_val = revision.value_json
            try:
                if isinstance(json_val, str):
                    json_val = json.loads(json_val)
                raw_value = json_val.get("value") if isinstance(json_val, dict) else str(json_val)
            except (json.JSONDecodeError, TypeError):
                raw_value = str(revision.value_json)

        if raw_value in (None, ""):
            continue

        facts.append(
            {
                "path": path,
                "scope": {},
                "raw_value": raw_value,
                "data_type": data_type,
                "unit": None,
                "source": {"file": "answer", "locator": question_code},
                "confidence": "STATED",
            }
        )

    return {
        "app_id": str(application.id),
        "facts": facts,
        "interfaces": [],
        "inputs": [],
    }


def extract_topology_data(session: Session, intake_id: str) -> TopologyData:
    """
    Extract and resolve topology data from the database for an intake.

    Runs the database extraction, then the same normalize/build_issues/
    select_values/compose_names pipeline the POC uses, and returns a
    ``TopologyData`` for diagram filling and gap reporting.
    """
    extracted = extract_topology_facts(session, intake_id)
    issue_rules = _load_fact_map(_FACT_MAP_PATH)
    naming_config = _load_naming_config(_NAMING_CONFIG_PATH)

    resolved = resolve_facts(
        app_id=extracted["app_id"],
        facts=extracted["facts"],
        interfaces=extracted["interfaces"],
        inputs=extracted["inputs"],
        issue_rules=issue_rules,
        naming_config=naming_config,
        site={},
        path_to_token=PATH_TO_TOKEN,
    )

    selected = resolved["selected"]
    tokens: dict[str, str] = {
        name: str(value) for name, value in resolved["tokens"].items()
    }
    missing_tokens = [
        token_name
        for path, token_name in PATH_TO_TOKEN.items()
        if str(tokens.get(token_name, "")) == placeholder(token_name)
    ]

    application_name = str(selected.get("app.name", ""))

    return TopologyData(
        app_id=resolved["app_id"],
        app_name=application_name,
        app_acronym=selected.get("app.acronym"),
        correlation_id=selected.get("app.correlation_id"),
        tokens=tokens,
        missing_tokens=missing_tokens,
        issues=resolved["issues"],
    )


def get_intake_tokens(session: Session, intake_id: str) -> dict[str, str]:
    """
    Get tokens for an intake as a simple dict.

    This is a convenience function for diagram filling.
    """
    data = extract_topology_data(session, intake_id)
    return data.tokens
