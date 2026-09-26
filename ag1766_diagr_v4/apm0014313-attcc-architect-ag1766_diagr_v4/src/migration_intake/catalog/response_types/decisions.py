"""
Decision response types (R04).

This module implements the five structured decision response types:
- BOOLEAN_WITH_RATIONALE: Choice plus required rationale
- CONTROLLED_SET: Repeatable controlled rows with uniqueness
- SINGLE_SELECT_PER_COMPONENT: Component table with selections
- DECISION_WITH_PERSON: Decision plus owner/person
- APPROVAL: Restricted decision command (is_computed=True)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from migration_intake.catalog.response_types.base import (
    ComparisonResult,
    ParseResult,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)


class BooleanWithRationaleType(ResponseTypeBase):
    """
    Boolean choice with required rationale.

    Canonical shape: {value: YES|NO|UNKNOWN, rationale: string}

    Used for controls like SEC-007, RES-006 where a policy-required
    rationale must accompany the boolean choice.
    """

    code = ResponseTypeCodes.BOOLEAN_WITH_RATIONALE
    schema_version = "1.0"
    editor_key = "boolean_with_rationale_editor"
    display_key = "boolean_with_rationale_display"
    is_computed = False

    ALLOWED_VALUES = frozenset({"YES", "NO", "UNKNOWN"})

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate boolean with rationale value."""
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check for _unknown marker
        if value.get("_unknown"):
            return ValidationResult.valid()

        # Validate value field
        val = value.get("value")
        if val is None:
            errors.append("Value is required")
            field_errors["value"] = ["Value is required"]
        elif val not in self.ALLOWED_VALUES:
            errors.append(f"Value must be one of: {', '.join(sorted(self.ALLOWED_VALUES))}")
            field_errors["value"] = [f"Invalid value: {val}"]

        # Validate rationale field - required when value is YES or NO
        rationale = value.get("rationale")
        if val in ("YES", "NO") and (
            rationale is None or (isinstance(rationale, str) and not rationale.strip())
        ):
            errors.append("Rationale is required when value is YES or NO")
            field_errors["rationale"] = ["Rationale is required"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize boolean with rationale value."""
        if value is None:
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        result: dict[str, Any] = {}

        # Normalize value to uppercase
        val = value.get("value")
        if val is not None:
            result["value"] = str(val).strip().upper()

        # Trim whitespace from rationale
        rationale = value.get("rationale")
        if rationale is not None:
            result["rationale"] = str(rationale).strip()

        return result

    def compare(self, old: dict[str, Any], new: dict[str, Any]) -> ComparisonResult:
        """Compare two boolean with rationale values field by field."""
        old_norm = self.normalize(old) if old else None
        new_norm = self.normalize(new) if new else None

        if old_norm == new_norm:
            return ComparisonResult.equal()

        differences: list[dict[str, Any]] = []

        old_val = old_norm.get("value") if old_norm else None
        new_val = new_norm.get("value") if new_norm else None
        if old_val != new_val:
            differences.append({"field": "value", "old": old_val, "new": new_val})

        old_rationale = old_norm.get("rationale") if old_norm else None
        new_rationale = new_norm.get("rationale") if new_norm else None
        if old_rationale != new_rationale:
            differences.append({"field": "rationale", "old": old_rationale, "new": new_rationale})

        return ComparisonResult.different(differences) if differences else ComparisonResult.equal()

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission."""
        try:
            value = form_data.get("value")
            rationale = form_data.get("rationale")

            result: dict[str, Any] = {}
            if value is not None:
                result["value"] = str(value).strip().upper()
            if rationale is not None:
                result["rationale"] = str(rationale).strip()

            return ParseResult.success(result, raw_input=form_data)
        except Exception as e:
            return ParseResult.failure([f"Form parse error: {e}"], raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, _context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {})

        # Expect format: "YES|NO|UNKNOWN: rationale text" or just "YES|NO|UNKNOWN"
        cell_str = str(cell_value).strip()

        # Try to parse "VALUE: rationale" format
        match = re.match(r"^(YES|NO|UNKNOWN)(?:\s*:\s*(.*))?$", cell_str, re.IGNORECASE)
        if match:
            val = match.group(1).upper()
            rationale = match.group(2)
            result: dict[str, Any] = {"value": val}
            if rationale:
                result["rationale"] = rationale.strip()
            return ParseResult.success(result, raw_input=cell_value)

        return ParseResult.failure(
            [
                f"Invalid format. Expected 'YES|NO|UNKNOWN: rationale' or "
                f"'YES|NO|UNKNOWN', got: {cell_str}"
            ],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty/blank value."""
        return None

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"value": "UNKNOWN", "rationale": ""}


class ControlledSetType(ResponseTypeBase):
    """
    Repeatable controlled rows with uniqueness by code/scope.

    Canonical shape: {items: [{code, detail?, scope?}]}

    Used for controls like SEC-008, TGT-002 where multiple controlled
    values can be selected with optional detail and scope.
    """

    code = ResponseTypeCodes.CONTROLLED_SET
    schema_version = "1.0"
    editor_key = "controlled_set_editor"
    display_key = "controlled_set_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate controlled set value."""
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check for _unknown marker
        if value.get("_unknown"):
            return ValidationResult.valid()

        items = value.get("items")
        if items is None:
            return ValidationResult.valid()

        if not isinstance(items, list):
            return ValidationResult.invalid(
                ["Items must be a list"],
                {"items": ["Items must be a list"]},
            )

        # Check uniqueness by code/scope
        seen_keys: set[tuple[str, str]] = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"Item {i} must be an object")
                field_errors[f"items[{i}]"] = ["Item must be an object"]
                continue

            code = item.get("code")
            if code is None or (isinstance(code, str) and not code.strip()):
                errors.append(f"Item {i} missing required code")
                field_errors[f"items[{i}].code"] = ["Code is required"]
                continue

            # Build uniqueness key from code and scope
            scope = item.get("scope")
            scope_key = self._scope_to_key(scope)
            unique_key = (str(code).strip().upper(), scope_key)

            if unique_key in seen_keys:
                errors.append(f"Duplicate code/scope combination: {code}")
                field_errors[f"items[{i}].code"] = ["Duplicate code/scope"]
            seen_keys.add(unique_key)

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def _scope_to_key(self, scope: Any) -> str:
        """Convert scope to a hashable key for uniqueness checking."""
        if scope is None:
            return ""
        if isinstance(scope, dict):
            # Sort keys for consistent hashing
            return str(sorted(scope.items()))
        return str(scope)

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize controlled set value."""
        if value is None:
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        items = value.get("items")
        if items is None:
            return {"items": []}

        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            norm_item: dict[str, Any] = {}

            # Normalize code to uppercase
            code = item.get("code")
            if code is not None:
                norm_item["code"] = str(code).strip().upper()

            # Trim detail whitespace
            detail = item.get("detail")
            if detail is not None:
                norm_item["detail"] = str(detail).strip()

            # Keep scope as-is (structured)
            scope = item.get("scope")
            if scope is not None:
                norm_item["scope"] = scope

            normalized_items.append(norm_item)

        # Sort by code for canonical ordering
        normalized_items.sort(key=lambda x: (x.get("code", ""), self._scope_to_key(x.get("scope"))))

        return {"items": normalized_items}

    def compare(self, old: dict[str, Any], new: dict[str, Any]) -> ComparisonResult:
        """Compare two controlled set values."""
        old_norm = self.normalize(old) if old else {"items": []}
        new_norm = self.normalize(new) if new else {"items": []}

        if old_norm == new_norm:
            return ComparisonResult.equal()

        differences: list[dict[str, Any]] = []

        old_items = old_norm.get("items", [])
        new_items = new_norm.get("items", [])

        # Build maps by code/scope for comparison
        old_map = {(i.get("code"), self._scope_to_key(i.get("scope"))): i for i in old_items}
        new_map = {(i.get("code"), self._scope_to_key(i.get("scope"))): i for i in new_items}

        all_keys = set(old_map.keys()) | set(new_map.keys())

        for key in sorted(all_keys):
            old_item = old_map.get(key)
            new_item = new_map.get(key)

            if old_item != new_item:
                differences.append({
                    "field": f"items[{key[0]}]",
                    "old": old_item,
                    "new": new_item,
                })

        return ComparisonResult.different(differences) if differences else ComparisonResult.equal()

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission."""
        try:
            items = form_data.get("items", [])
            if not isinstance(items, list):
                return ParseResult.failure(["Items must be a list"], raw_input=form_data)

            parsed_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                parsed_item: dict[str, Any] = {}
                if "code" in item:
                    parsed_item["code"] = str(item["code"]).strip().upper()
                if "detail" in item:
                    parsed_item["detail"] = str(item["detail"]).strip()
                if "scope" in item:
                    parsed_item["scope"] = item["scope"]
                parsed_items.append(parsed_item)

            return ParseResult.success({"items": parsed_items}, raw_input=form_data)
        except Exception as e:
            return ParseResult.failure([f"Form parse error: {e}"], raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, _context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {"items": []})

        # Expect format: "CODE1, CODE2" or "CODE1: detail1; CODE2: detail2"
        cell_str = str(cell_value).strip()

        items: list[dict[str, Any]] = []
        # Split by semicolon for multiple items
        parts = cell_str.split(";")
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check for "CODE: detail" format
            if ":" in part:
                code_part, detail_part = part.split(":", 1)
                items.append({
                    "code": code_part.strip().upper(),
                    "detail": detail_part.strip(),
                })
            else:
                # Just codes separated by comma
                for code in part.split(","):
                    code = code.strip()
                    if code:
                        items.append({"code": code.upper()})

        return ParseResult.success({"items": items}, raw_input=cell_value)

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty/blank value."""
        return {"items": []}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}


class SingleSelectPerComponentType(ResponseTypeBase):
    """
    Component table with selections per component.

    Canonical shape: {components: [{component_key, selection, rationale?}]}

    Used for controls like TGT-001 where each component needs
    a selection with optional rationale.
    """

    code = ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT
    schema_version = "1.0"
    editor_key = "single_select_per_component_editor"
    display_key = "single_select_per_component_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate single select per component value."""
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check for _unknown marker
        if value.get("_unknown"):
            return ValidationResult.valid()

        components = value.get("components")
        if components is None:
            return ValidationResult.valid()

        if not isinstance(components, list):
            return ValidationResult.invalid(
                ["Components must be a list"],
                {"components": ["Components must be a list"]},
            )

        # Check uniqueness by component_key
        seen_keys: set[str] = set()
        for i, comp in enumerate(components):
            if not isinstance(comp, dict):
                errors.append(f"Component {i} must be an object")
                field_errors[f"components[{i}]"] = ["Component must be an object"]
                continue

            comp_key = comp.get("component_key")
            if comp_key is None or (isinstance(comp_key, str) and not comp_key.strip()):
                errors.append(f"Component {i} missing required component_key")
                field_errors[f"components[{i}].component_key"] = ["Component key is required"]
                continue

            key_normalized = str(comp_key).strip().upper()
            if key_normalized in seen_keys:
                errors.append(f"Duplicate component_key: {comp_key}")
                field_errors[f"components[{i}].component_key"] = ["Duplicate component key"]
            seen_keys.add(key_normalized)

            # Selection is required
            selection = comp.get("selection")
            if selection is None or (isinstance(selection, str) and not selection.strip()):
                errors.append(f"Component {i} missing required selection")
                field_errors[f"components[{i}].selection"] = ["Selection is required"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize single select per component value."""
        if value is None:
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        components = value.get("components")
        if components is None:
            return {"components": []}

        normalized_components: list[dict[str, Any]] = []
        for comp in components:
            if not isinstance(comp, dict):
                continue

            norm_comp: dict[str, Any] = {}

            # Normalize component_key to uppercase
            comp_key = comp.get("component_key")
            if comp_key is not None:
                norm_comp["component_key"] = str(comp_key).strip().upper()

            # Normalize selection to uppercase
            selection = comp.get("selection")
            if selection is not None:
                norm_comp["selection"] = str(selection).strip().upper()

            # Trim rationale whitespace
            rationale = comp.get("rationale")
            if rationale is not None:
                norm_comp["rationale"] = str(rationale).strip()

            normalized_components.append(norm_comp)

        # Sort by component_key for canonical ordering
        normalized_components.sort(key=lambda x: x.get("component_key", ""))

        return {"components": normalized_components}

    def compare(self, old: dict[str, Any], new: dict[str, Any]) -> ComparisonResult:
        """Compare two single select per component values."""
        old_norm = self.normalize(old) if old else {"components": []}
        new_norm = self.normalize(new) if new else {"components": []}

        if old_norm == new_norm:
            return ComparisonResult.equal()

        differences: list[dict[str, Any]] = []

        old_comps = old_norm.get("components", [])
        new_comps = new_norm.get("components", [])

        # Build maps by component_key
        old_map = {c.get("component_key"): c for c in old_comps}
        new_map = {c.get("component_key"): c for c in new_comps}

        all_keys = set(old_map.keys()) | set(new_map.keys())

        for key in sorted(all_keys):
            old_comp = old_map.get(key)
            new_comp = new_map.get(key)

            if old_comp != new_comp:
                differences.append({
                    "field": f"components[{key}]",
                    "old": old_comp,
                    "new": new_comp,
                })

        return ComparisonResult.different(differences) if differences else ComparisonResult.equal()

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission."""
        try:
            components = form_data.get("components", [])
            if not isinstance(components, list):
                return ParseResult.failure(["Components must be a list"], raw_input=form_data)

            parsed_components: list[dict[str, Any]] = []
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                parsed_comp: dict[str, Any] = {}
                if "component_key" in comp:
                    parsed_comp["component_key"] = str(comp["component_key"]).strip().upper()
                if "selection" in comp:
                    parsed_comp["selection"] = str(comp["selection"]).strip().upper()
                if "rationale" in comp:
                    parsed_comp["rationale"] = str(comp["rationale"]).strip()
                parsed_components.append(parsed_comp)

            return ParseResult.success({"components": parsed_components}, raw_input=form_data)
        except Exception as e:
            return ParseResult.failure([f"Form parse error: {e}"], raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, _context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {"components": []})

        # Expect format: "COMP1=SELECTION1; COMP2=SELECTION2: rationale"
        cell_str = str(cell_value).strip()

        components: list[dict[str, Any]] = []
        parts = cell_str.split(";")
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Parse "COMP=SELECTION" or "COMP=SELECTION: rationale"
            if "=" not in part:
                continue

            key_part, rest = part.split("=", 1)
            comp_key = key_part.strip().upper()

            # Check for rationale after colon
            if ":" in rest:
                selection_part, rationale_part = rest.split(":", 1)
                components.append({
                    "component_key": comp_key,
                    "selection": selection_part.strip().upper(),
                    "rationale": rationale_part.strip(),
                })
            else:
                components.append({
                    "component_key": comp_key,
                    "selection": rest.strip().upper(),
                })

        return ParseResult.success({"components": components}, raw_input=cell_value)

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty/blank value."""
        return {"components": []}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}


class DecisionWithPersonType(ResponseTypeBase):
    """
    Decision plus owner/person.

    Canonical shape: {decision, owner, rationale?, decided_at?}

    Used for controls like MIG-001 where a decision requires
    an owner. Note: manual identity is not authenticated identity.
    """

    code = ResponseTypeCodes.DECISION_WITH_PERSON
    schema_version = "1.0"
    editor_key = "decision_with_person_editor"
    display_key = "decision_with_person_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate decision with person value."""
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check for _unknown marker
        if value.get("_unknown"):
            return ValidationResult.valid()

        # Decision is required
        decision = value.get("decision")
        if decision is None or (isinstance(decision, str) and not decision.strip()):
            errors.append("Decision is required")
            field_errors["decision"] = ["Decision is required"]

        # Owner is required
        owner = value.get("owner")
        if owner is None or (isinstance(owner, str) and not owner.strip()):
            errors.append("Owner is required")
            field_errors["owner"] = ["Owner is required"]

        # Validate decided_at if present (ISO 8601 format)
        decided_at = value.get("decided_at")
        if decided_at is not None and decided_at != "":
            try:
                if isinstance(decided_at, str):
                    # Try to parse ISO format
                    datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
            except ValueError:
                errors.append("decided_at must be a valid ISO 8601 datetime")
                field_errors["decided_at"] = ["Invalid datetime format"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize decision with person value."""
        if value is None:
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        result: dict[str, Any] = {}

        # Normalize decision to uppercase
        decision = value.get("decision")
        if decision is not None:
            result["decision"] = str(decision).strip().upper()

        # Trim owner whitespace (preserve case for names)
        owner = value.get("owner")
        if owner is not None:
            result["owner"] = str(owner).strip()

        # Trim rationale whitespace
        rationale = value.get("rationale")
        if rationale is not None:
            result["rationale"] = str(rationale).strip()

        # Keep decided_at as-is (ISO format)
        decided_at = value.get("decided_at")
        if decided_at is not None:
            result["decided_at"] = decided_at

        return result

    def compare(self, old: dict[str, Any], new: dict[str, Any]) -> ComparisonResult:
        """Compare two decision with person values field by field."""
        old_norm = self.normalize(old) if old else None
        new_norm = self.normalize(new) if new else None

        if old_norm == new_norm:
            return ComparisonResult.equal()

        differences: list[dict[str, Any]] = []
        fields = ["decision", "owner", "rationale", "decided_at"]

        for field in fields:
            old_val = old_norm.get(field) if old_norm else None
            new_val = new_norm.get(field) if new_norm else None
            if old_val != new_val:
                differences.append({"field": field, "old": old_val, "new": new_val})

        return ComparisonResult.different(differences) if differences else ComparisonResult.equal()

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission."""
        try:
            result: dict[str, Any] = {}

            if "decision" in form_data:
                result["decision"] = str(form_data["decision"]).strip().upper()
            if "owner" in form_data:
                result["owner"] = str(form_data["owner"]).strip()
            if "rationale" in form_data:
                result["rationale"] = str(form_data["rationale"]).strip()
            if "decided_at" in form_data:
                result["decided_at"] = form_data["decided_at"]

            return ParseResult.success(result, raw_input=form_data)
        except Exception as e:
            return ParseResult.failure([f"Form parse error: {e}"], raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, _context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {})

        # Expect format: "DECISION by Owner Name" or "DECISION by Owner Name: rationale"
        cell_str = str(cell_value).strip()

        # Try to parse "DECISION by Owner" format
        match = re.match(r"^(\w+)\s+by\s+(.+?)(?:\s*:\s*(.*))?$", cell_str, re.IGNORECASE)
        if match:
            decision = match.group(1).upper()
            owner = match.group(2).strip()
            rationale = match.group(3)

            result: dict[str, Any] = {
                "decision": decision,
                "owner": owner,
            }
            if rationale:
                result["rationale"] = rationale.strip()

            return ParseResult.success(result, raw_input=cell_value)

        return ParseResult.failure(
            [f"Invalid format. Expected 'DECISION by Owner Name', got: {cell_str}"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty/blank value."""
        return None

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}


class ApprovalType(ResponseTypeBase):
    """
    Restricted decision command with server-assigned actor/time.

    Canonical shape: {decision, decided_by, decided_at, rationale?, evidence_refs[]}

    Used for controls like WAV-009, APR-002..004. This type is computed
    (is_computed=True) meaning it rejects direct saves - values must come
    from approval commands with server-assigned actor and timestamp.

    Never accepted from workbook as approval.
    """

    code = ResponseTypeCodes.APPROVAL
    schema_version = "1.0"
    editor_key = "approval_editor"
    display_key = "approval_display"
    is_computed = True  # Rejects direct saves

    ALLOWED_DECISIONS = frozenset({"APPROVED", "REJECTED", "DEFERRED", "PENDING"})

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate approval value."""
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check for _unknown marker
        if value.get("_unknown"):
            return ValidationResult.valid()

        # Decision is required
        decision = value.get("decision")
        if decision is None or (isinstance(decision, str) and not decision.strip()):
            errors.append("Decision is required")
            field_errors["decision"] = ["Decision is required"]
        elif decision not in self.ALLOWED_DECISIONS:
            errors.append(f"Decision must be one of: {', '.join(sorted(self.ALLOWED_DECISIONS))}")
            field_errors["decision"] = [f"Invalid decision: {decision}"]

        # decided_by is required (server-assigned)
        decided_by = value.get("decided_by")
        if decided_by is None or (isinstance(decided_by, str) and not decided_by.strip()):
            errors.append("decided_by is required")
            field_errors["decided_by"] = ["decided_by is required"]

        # decided_at is required (server-assigned)
        decided_at = value.get("decided_at")
        if decided_at is None:
            errors.append("decided_at is required")
            field_errors["decided_at"] = ["decided_at is required"]
        else:
            try:
                if isinstance(decided_at, str):
                    datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
            except ValueError:
                errors.append("decided_at must be a valid ISO 8601 datetime")
                field_errors["decided_at"] = ["Invalid datetime format"]

        # evidence_refs must be a list if present
        evidence_refs = value.get("evidence_refs")
        if evidence_refs is not None and not isinstance(evidence_refs, list):
            errors.append("evidence_refs must be a list")
            field_errors["evidence_refs"] = ["evidence_refs must be a list"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize approval value."""
        if value is None:
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        result: dict[str, Any] = {}

        # Normalize decision to uppercase
        decision = value.get("decision")
        if decision is not None:
            result["decision"] = str(decision).strip().upper()

        # Keep decided_by as-is (server-assigned)
        decided_by = value.get("decided_by")
        if decided_by is not None:
            result["decided_by"] = str(decided_by).strip()

        # Keep decided_at as-is (server-assigned ISO format)
        decided_at = value.get("decided_at")
        if decided_at is not None:
            result["decided_at"] = decided_at

        # Trim rationale whitespace
        rationale = value.get("rationale")
        if rationale is not None:
            result["rationale"] = str(rationale).strip()

        # Keep evidence_refs as-is
        evidence_refs = value.get("evidence_refs")
        if evidence_refs is not None:
            result["evidence_refs"] = evidence_refs

        return result

    def compare(self, old: dict[str, Any], new: dict[str, Any]) -> ComparisonResult:
        """Compare two approval values field by field."""
        old_norm = self.normalize(old) if old else None
        new_norm = self.normalize(new) if new else None

        if old_norm == new_norm:
            return ComparisonResult.equal()

        differences: list[dict[str, Any]] = []
        fields = ["decision", "decided_by", "decided_at", "rationale", "evidence_refs"]

        for field in fields:
            old_val = old_norm.get(field) if old_norm else None
            new_val = new_norm.get(field) if new_norm else None
            if old_val != new_val:
                differences.append({"field": field, "old": old_val, "new": new_val})

        return ComparisonResult.different(differences) if differences else ComparisonResult.equal()

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """
        Parse HTML form submission.

        Note: Even though this parses form data, the is_computed=True flag
        means the application service will reject direct saves. Form parsing
        is provided for command validation.
        """
        try:
            result: dict[str, Any] = {}

            if "decision" in form_data:
                result["decision"] = str(form_data["decision"]).strip().upper()
            if "decided_by" in form_data:
                result["decided_by"] = str(form_data["decided_by"]).strip()
            if "decided_at" in form_data:
                result["decided_at"] = form_data["decided_at"]
            if "rationale" in form_data:
                result["rationale"] = str(form_data["rationale"]).strip()
            if "evidence_refs" in form_data:
                result["evidence_refs"] = form_data["evidence_refs"]

            return ParseResult.success(result, raw_input=form_data)
        except Exception as e:
            return ParseResult.failure([f"Form parse error: {e}"], raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, _context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value.

        APPROVAL type rejects workbook import - approvals must come from
        authenticated approval commands, not workbook data.
        """
        # Always reject workbook import for approvals
        return ParseResult.failure(
            ["Approval values cannot be imported from workbook. Use approval commands."],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty/blank value."""
        return None

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}
