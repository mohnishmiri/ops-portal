# AT&T Internal Interfaces: Protocol-Family Grouped Rendering — Design & Implementation Plan

Detailed design and TDD implementation plan to refactor the AT&T Internal Interfaces section from per-interface rendering to protocol-family grouped rendering, with comma-separated deduplicated labels, multi-port display, aggregated direction, and reusable patterns from drawpyo-main (MIT). This document is the canonical source of truth for agents and developers implementing the change.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Screenshot Comparison — Current vs Desired](#2-screenshot-comparison)
3. [Current Behavior — End-to-End Pipeline Trace](#3-current-behavior)
4. [Data-Field Mapping and Evidence](#4-data-field-mapping)
5. [Protocol Family Normalizer — Design](#5-protocol-family-normalizer)
6. [Grouping, Dedup, and Direction Aggregation — Design](#6-grouping-design)
7. [View Model — ProtocolFamilyGroup](#7-view-model)
8. [Rendering and Layout — Design](#8-rendering-and-layout)
9. [Reusable Code from drawpyo-main](#9-reusable-code-from-drawpyo)
10. [TDD Implementation Slices](#10-tdd-implementation-slices)
11. [Test Plan](#11-test-plan)
12. [Risks and Open Questions](#12-risks-and-open-questions)
13. [Acceptance Criteria](#13-acceptance-criteria)
14. [File Change Summary](#14-file-change-summary)

---

## 1. Executive Summary

### Problem

The current AT&T Internal Interfaces section in the HAF topology pipeline renders too many rows because it groups by the **exact protocol string plus port** `(norm_protocol, norm_port)`. Since the DB stores long, varied protocol strings (e.g., `"HTTPS(TLSv1.2)"`, `"Oracle Net TCPS(TLS1.2)"`, `"JDBC over TLS 1.2/TCP"`), interfaces that share a protocol family but differ in wording or port produce separate groups. For CCPM this produces ~12 narrow rows instead of the consolidated ~6 rows shown in the desired layout.

### Solution

Introduce a **protocol-family normalizer** that maps ~15 distinct protocol strings to ~7 families (`HTTPS`, `ORACLE_DB`, `SQL_DB`, `CONNECT_DIRECT`, `ORACLE_GG`, `SFTP`, `AMQP`, `POSTGRESQL`). Change the grouping key from `(exact_protocol, port)` to `protocol_family` alone, merging all ports of the same family into one row. Render comma-separated deduplicated application labels. Aggregate direction across the group (`IN`, `OUT`, or `IN/OUT`). Place incomplete records (missing protocol/port) in a visible Unknown group.

### User-Confirmed Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Grouping key | **Protocol family** (merge same-protocol ports) | Matches Screenshot 2 layout where 443+8447 are one row |
| Label format | **Comma-separated** | `"APP1 (ID1), APP2 (ID2)"` per Screenshot 2 |
| Label dedup | **Yes, deduplicate** within each group | Same app on multiple ports appears once |
| Missing fields | **Unknown group** at bottom with `?` markers | Visible but clearly flagged |
| Protocol display | **Not in box** — via connector color only | Port box shows port+direction; protocol is in the legend |
| ORACLE RAC | **Ignore for now** — use standard app grouping | Likely a manual edit in reference diagram |

---

## 2. Screenshot Comparison

### Confirmed Observations

| Aspect | Screenshot 1 (Current) | Screenshot 2 (Desired) |
|---|---|---|
| **Row count** | ~12 rows | ~6 rows |
| **Grouping** | One row per `(exact_protocol, port)` | One row per protocol family (merging ports) |
| **Port label** | Single port per row (e.g., `"443"`) | Multiple ports in one label (e.g., `"443 8447"`) |
| **Direction** | Per-interface or per-slot direction | Aggregated: `IN`, `OUT`, or `IN/OUT` |
| **Label format** | Newline-separated (`&#10;`) in dashed box | Comma-separated, wrapped text |
| **Dedup** | Duplicates visible (e.g., `"CCWEB (18200)"` x2) | Appears deduplicated |
| **Incomplete** | `"ImE FLEX (15977)"` shows `"2 OUT"` — data error | Not visible (excluded or in Unknown group) |
| **Connectors** | Individual colored arrows per row | Colored arrows per grouped row |
| **Box sizing** | Fixed small boxes per entry | Boxes sized to content |

### Unresolved Visual Ambiguities

These cannot be reliably determined from the screenshots alone. Proposed defaults are given; override during implementation if a visual check shows a better option.

1. **Exact connector exit/entry points** when rows merge — propose: horizontal from right edge of left box to right edge of container
2. **Left box width** — propose: fixed 180px with `whiteSpace=wrap`
3. **Inter-row spacing** — propose: 12px (current value in LAYOUT config)
4. **Container band auto-resize** — propose: defer; keep current band height
5. **Font size** — propose: keep `fontSize=10` for left box, `fontSize=11` bold for label

---

## 3. Current Behavior

### Data Flow Trace

```
InterfaceRecord (DB table: interfaces, 33 columns)
  │
  ▼
haf_extractor.extract_haf_data()                    ← reads DB, creates candidates
  │  calls → interface_normalization.create_interface_candidate()
  │  calls → interface_normalization.group_interfaces_by_protocol_port()
  │
  ▼
haf_pipeline.fill_haf_template()                    ← orchestrates fill
  │  calls → att_internal_generator.generate_att_internal_rows()  ← GENERATES mxCells
  │  calls → fill_interface_regions(skip_internal=True)           ← skips INTERNAL
  │
  ▼
haf_service.generate_haf_topology()                 ← service layer: extract + fill
  │
  ▼
HafTopologyResult (filled_xml bytes, mutations, gaps)
```

### Key Files — Exact Locations

| File | Key Function/Class | Line Range | What It Does |
|---|---|---|---|
| `src/migration_intake/topology/haf_extractor.py` | `extract_haf_data()` | 86-223 | Reads `InterfaceRecord` from DB, creates `InterfaceCandidate` objects, calls `group_interfaces_by_protocol_port()`, returns `HafExtractionResult` |
| `src/migration_intake/topology/interface_normalization.py` | `create_interface_candidate()` | 269-301 | Normalizes raw DB fields: location→category via `HAF_LOCATION_ALIASES`, direction via `DIRECTION_ALIASES`, protocol/port via `.strip().upper()` |
| `src/migration_intake/topology/interface_normalization.py` | `group_interfaces_by_protocol_port()` | 304-366 | **THE FUNCTION TO REPLACE.** Groups candidates by `(norm_protocol, norm_port)` key. Populates direction-specific entry lists. Sorts deterministically. |
| `src/migration_intake/topology/interface_normalization.py` | `InterfaceGroup` | 103-145 | Dataclass: `protocol`, `port`, `entries_inbound/outbound/bidirectional`, `sort_key`. **TO BE SUPPLEMENTED by `ProtocolFamilyGroup`.** |
| `src/migration_intake/topology/att_internal_generator.py` | `generate_att_internal_rows()` | 224-373 | Creates 3 mxCell XML elements per group (left box, label box, connector edge) inside the ATT band container. Uses `_all_group_entries()` for label collection. **PRIMARY RENDERING FILE TO MODIFY.** |
| `src/migration_intake/topology/att_internal_generator.py` | `_all_group_entries()` | 200-221 | Collects deduplicated `(app, corr_id)` pairs from an `InterfaceGroup`. **TO ADAPT for `ProtocolFamilyGroup`.** |
| `src/migration_intake/topology/att_internal_generator.py` | `_left_height()` | 195-197 | Calculates left box height from interface count × `line_height`. **TO REPLACE with wrapping-aware estimator.** |
| `src/migration_intake/topology/att_internal_generator.py` | `LAYOUT` dict | 35-50 | Layout constants: `start_x`, `start_y`, `left_width`, `label_width`, etc. |
| `src/migration_intake/topology/att_internal_generator.py` | `PROTOCOL_COLORS` | 67-82 | Maps protocol keywords to hex colors. **TO EXTEND for protocol families.** |
| `src/migration_intake/topology/haf_pipeline.py` | `fill_haf_template()` | 614-717 | Orchestrator: calls `generate_att_internal_rows(tree, interface_groups)` at line 660. **CALL SITE TO UPDATE.** |
| `src/migration_intake/topology/haf_service.py` | `generate_haf_topology()` | 53-100 | Passes `extraction.interface_groups` to `fill_haf_template()`. **MAY NEED UPDATE if group type changes.** |
| `src/migration_intake/topology/guide_policy.py` | `LOCATION_ALIASES` | 10-19 | Base location→category mapping. Read-only reference. |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` | OUTPOST_V1 | Full file | Profile config: interface_regions, protected_roles, placeholder_bindings. **PROTECTED: `att_internal_interfaces_band` is listed.** |

### Current Grouping Key (THE ROOT CAUSE)

```python
# interface_normalization.py line 329 — current code
key = (candidate.norm_protocol, candidate.norm_port)
```

This produces ~12 groups for CCPM because:
- Port 443 with `"HTTPS(TLSV1.2)"` and port 8447 with `"HTTPS(TLSV1.2)"` = **2 separate groups**
- Port 1521 with `"JDBC OVER TLS 1.2/TCP"` and port 1521 with `"ORACLE NET TCPS(TLS1.2)"` = **2 separate groups** (same port, different protocol string)

---

## 4. Data-Field Mapping

Verified from `models_interfaces.py`, the CCPM SQLite data, and normalization code:

| Business Term | DB Column | Type | Current Normalization | Proposed Change |
|---|---|---|---|---|
| Interface System Location | `interface_system_location` | `String(255)`, nullable | `.strip().upper()` → `HAF_LOCATION_ALIASES` → category | **None** — already correct |
| Target Protocol | `target_protocol` | `String(255)`, nullable | `.strip().upper()` only | **ADD: `normalize_protocol_family()` → family key** |
| Future Port | `future_port` | `String(32)`, nullable | `.strip()` only | **None** — ports merge at group level |
| Direction | `data_traffic_direction` | `String(32)`, nullable | `.strip().upper()` → `DIRECTION_ALIASES` → canonical | **None** — aggregation at group level |
| App Acronym | `interface_app_acronym` | `String(255)`, nullable | None (passed through) | **None** |
| Correlation ID | `interface_correlation_id` | `String(255)`, not null | None (passed through) | **None** |

### CCPM Midrange Interface Data (Synthetic Representation)

For reference, the CCPM application has 24 Midrange-location interfaces. After protocol-family grouping, the expected output is:

| Protocol Family | Ports | Apps (deduped) | Direction |
|---|---|---|---|
| `HTTPS` | 443, 8447 | CPC, DITREX, eCDW, EDGE, OVALS GIS, Saart, uDAS | IN/OUT |
| `CONNECT_DIRECT` | 1364 | Mylogin, SOCS | IN/OUT |
| `ORACLE_DB` | 1521 | CCPM, CCR-Relational - CCR-R, MSTRS | IN/OUT |
| `SQL_DB` | 1433 | ATT VERINT CQM, EDW, ORACLE SCM | IN |
| `ORACLE_GG` | 7809 | Enabler LS, LS CRM, LS-OMS, OPUS - C, TLG-MOB | IN |
| `SFTP` | 22 | CCQT | IN |
| `UNKNOWN` | ? | ImE FLEX | ? |

**7 rows** (down from ~12), matching the ~6-7 rows visible in Screenshot 2.

---

## 5. Protocol Family Normalizer — Design

### New Function: `normalize_protocol_family()`

Location: `src/migration_intake/topology/interface_normalization.py`

```python
import re

# Ordered from most-specific to least-specific.
# First match wins. Order matters: "GOLDENGATE" must match before "ORACLE" fallthrough.
PROTOCOL_FAMILY_PATTERNS: list[tuple[str, str]] = [
    (r"GOLDENGATE|GOLDEN[\s._-]?GATE", "ORACLE_GG"),
    (r"JDBC|ORACLE[\s._-]?NET|ORACLE[\s._-]?NATIVE", "ORACLE_DB"),
    (r"ODBC|SQL[\s._-]?SERVER", "SQL_DB"),
    (r"CONNECT[\s._-]?DIRECT", "CONNECT_DIRECT"),
    (r"POSTGRES", "POSTGRESQL"),
    (r"AMQP", "AMQP"),
    (r"SFTP|SSH", "SFTP"),
    (r"HTTPS|HTTP", "HTTPS"),
]


def normalize_protocol_family(protocol: str | None) -> str:
    """Normalize a raw protocol string to a protocol family key.

    Uses ordered regex matching. First match wins.

    Args:
        protocol: Raw protocol value (e.g., "HTTPS(TLSv1.2)").

    Returns:
        Family key (e.g., "HTTPS", "ORACLE_DB", "UNKNOWN").
    """
    if not protocol:
        return "UNKNOWN"
    upper = protocol.strip().upper()
    if not upper:
        return "UNKNOWN"
    for pattern, family in PROTOCOL_FAMILY_PATTERNS:
        if re.search(pattern, upper):
            return family
    return "OTHER"
```

### Verification Against CCPM Data

| Raw Protocol (from DB) | Uppercase | Regex Match | Family |
|---|---|---|---|
| `"HTTPS(TLSv1.2)"` | `"HTTPS(TLSV1.2)"` | `HTTPS` | `HTTPS` |
| `"Connect:Direct Secure+ using TLS 1.2"` | `"CONNECT:DIRECT SECURE+ USING TLS 1.2"` | `CONNECT[\s._-]?DIRECT` | `CONNECT_DIRECT` |
| `"JDBC over TLS 1.2/TCP"` | `"JDBC OVER TLS 1.2/TCP"` | `JDBC` | `ORACLE_DB` |
| `"Oracle Net TCPS(TLS1.2)"` | `"ORACLE NET TCPS(TLS1.2)"` | `ORACLE[\s._-]?NET` | `ORACLE_DB` |
| `"Oracle Native Encryption(TLS1.2)"` | `"ORACLE NATIVE ENCRYPTION(TLS1.2)"` | `ORACLE[\s._-]?NATIVE` | `ORACLE_DB` |
| `"Oracle GoldenGate secured with TLS1.2"` | `"ORACLE GOLDENGATE SECURED WITH TLS1.2"` | `GOLDENGATE` | `ORACLE_GG` |
| `"ODBC(TCPS over TLS) TLS1.2"` | `"ODBC(TCPS OVER TLS) TLS1.2"` | `ODBC` | `SQL_DB` |
| `"SQL Server over TLS 1.2/TCP"` | `"SQL SERVER OVER TLS 1.2/TCP"` | `SQL[\s._-]?SERVER` | `SQL_DB` |
| `"SFTP using OpenSSH SSH-2"` | `"SFTP USING OPENSSH SSH-2"` | `SFTP` | `SFTP` |
| `"AMQP 1.0 over TLS 1.2"` | `"AMQP 1.0 OVER TLS 1.2"` | `AMQP` | `AMQP` |
| `"PostgreSQL SSL/TLS(TLS1.2)"` | `"POSTGRESQL SSL/TLS(TLS1.2)"` | `POSTGRES` | `POSTGRESQL` |
| `None` / `""` | — | — | `UNKNOWN` |

---

## 6. Grouping, Dedup, and Direction Aggregation — Design

### New Function: `group_interfaces_by_protocol_family()`

Location: `src/migration_intake/topology/interface_normalization.py`

This function **supplements** (does not replace) `group_interfaces_by_protocol_port()`. The old function is kept for backward compatibility; the new one is called from the extractor when protocol-family grouping is desired.

```
FUNCTION group_interfaces_by_protocol_family(
    candidates: List[InterfaceCandidate],
    category_filter: str | None = "INTERNAL"
) -> List[ProtocolFamilyGroup]:

    # Step 1: Filter to target category
    filtered = [c for c in candidates if category_filter is None
                or c.norm_category == category_filter]

    # Step 2: Separate complete vs incomplete
    complete = [c for c in filtered
                if c.norm_port and normalize_protocol_family(c.norm_protocol) != "UNKNOWN"]
    incomplete = [c for c in filtered
                  if not c.norm_port or normalize_protocol_family(c.norm_protocol) == "UNKNOWN"]

    # Step 3: Group complete records by protocol family
    groups: dict[str, ProtocolFamilyGroup] = {}
    FOR EACH candidate IN complete:
        family = normalize_protocol_family(candidate.norm_protocol)
        IF family NOT IN groups:
            groups[family] = ProtocolFamilyGroup(family=family)
        groups[family].add_candidate(candidate)

    # Step 4: Build Unknown group for incomplete records
    IF incomplete:
        unknown = ProtocolFamilyGroup(family="UNKNOWN")
        FOR EACH candidate IN incomplete:
            unknown.add_candidate(candidate)
        groups["UNKNOWN"] = unknown

    # Step 5: Sort deterministically and return
    RETURN sorted(groups.values(), key=lambda g: g.sort_key)
```

### Direction Aggregation Logic

```
FUNCTION aggregate_direction(candidates: List[InterfaceCandidate]) -> str:
    directions = {c.norm_direction for c in candidates}
    has_in = "INBOUND" in directions
    has_out = "OUTBOUND" in directions
    has_bidir = "BIDIRECTIONAL" in directions

    IF has_bidir OR (has_in AND has_out):
        RETURN "IN/OUT"
    ELIF has_in:
        RETURN "IN"
    ELIF has_out:
        RETURN "OUT"
    ELSE:
        RETURN "?"
```

### Label Deduplication

Within each `ProtocolFamilyGroup`, labels are deduplicated by `(app_acronym, correlation_id)` tuple. The same app CAN appear in multiple protocol-family groups (if it uses multiple protocols). Labels are sorted alphabetically for determinism.

---

## 7. View Model — ProtocolFamilyGroup

Location: `src/migration_intake/topology/interface_normalization.py`

```python
@dataclass
class ProtocolFamilyGroup:
    """A group of INTERNAL interfaces sharing the same protocol family.

    All ports for the family are merged into one row. Direction is aggregated.
    Application labels are deduplicated and comma-separated.
    """
    family: str              # "HTTPS", "ORACLE_DB", "SFTP", "UNKNOWN", etc.
    candidates: list[InterfaceCandidate] = field(default_factory=list)

    # Computed on finalize():
    ports: list[str] = field(default_factory=list)          # sorted: ["443", "8447"]
    direction: str = "?"                                     # "IN", "OUT", "IN/OUT", "?"
    labels: list[str] = field(default_factory=list)          # sorted, deduped
    connector_color: str = "#000000"                         # from FAMILY_COLORS map

    def add_candidate(self, candidate: InterfaceCandidate) -> None:
        self.candidates.append(candidate)

    def finalize(self) -> None:
        """Compute derived fields after all candidates are added."""
        # Ports: unique, sorted numerically (strings that look like ints)
        raw_ports = {c.norm_port for c in self.candidates if c.norm_port}
        self.ports = sorted(raw_ports, key=lambda p: (int(p) if p.isdigit() else 99999, p))

        # Direction: aggregated
        self.direction = _aggregate_direction(self.candidates)

        # Labels: deduplicated (app, corr_id), sorted
        seen: set[tuple[str, str]] = set()
        labels: list[str] = []
        for c in sorted(self.candidates,
                        key=lambda c: (c.interface_app_acronym or "", c.interface_correlation_id or "")):
            pair = (c.interface_app_acronym or "UNKNOWN", c.interface_correlation_id or "?")
            if pair not in seen:
                seen.add(pair)
                labels.append(f"{pair[0]} ({pair[1]})")
        self.labels = labels

        # Connector color from family
        self.connector_color = FAMILY_COLORS.get(self.family, "#000000")

    @property
    def port_display(self) -> str:
        """E.g., '443 8447' or '1521' or '?'"""
        return " ".join(self.ports) if self.ports else "?"

    @property
    def label_display(self) -> str:
        """Comma-separated: 'APP1 (ID1), APP2 (ID2), ...'"""
        return ", ".join(self.labels)

    @property
    def direction_display(self) -> str:
        return self.direction

    @property
    def sort_key(self) -> tuple[str, int]:
        """Deterministic sort: family name, then lowest port number."""
        min_port = min((int(p) for p in self.ports if p.isdigit()), default=99999)
        return (self.family, min_port)
```

### FAMILY_COLORS Map

```python
FAMILY_COLORS: dict[str, str] = {
    "HTTPS":          "#6666FF",   # Blue — matches legend
    "ORACLE_DB":      "#67AB9F",   # Teal — JDBC/Oracle Net
    "ORACLE_GG":      "#99004D",   # Dark magenta — GoldenGate
    "SQL_DB":         "#FF8000",   # Orange — ODBC/SQL Server
    "CONNECT_DIRECT": "#CC0000",   # Red
    "SFTP":           "#00CC66",   # Green — SSH/SFTP
    "AMQP":           "#9933CC",   # Purple
    "POSTGRESQL":     "#336791",   # PostgreSQL brand blue
    "OTHER":          "#666666",   # Gray
    "UNKNOWN":        "#999999",   # Light gray
}
```

---

## 8. Rendering and Layout — Design

### Shape Hierarchy (Per Group Row)

```
ATT Internal Interfaces Band (existing container cell, haf-role=att_internal_interfaces_band)
  │
  ├── Left App Box (mxCell vertex, parent=band_id)
  │     id:    att_internal_gen_{md5("left|{family}_{idx}")}
  │     value: comma-separated labels with whiteSpace=wrap
  │     style: dashed rectangle, light gray, left-aligned, fontSize=10
  │
  ├── Port/Direction Label (mxCell vertex, parent=band_id)
  │     id:    att_internal_gen_{md5("label|{family}_{idx}")}
  │     value: "{port_display}\n{direction_display}"
  │     style: white fill, black border, bold, centered, fontSize=11
  │
  └── Connector (mxCell edge, parent=band_id, source=left_id, target=band_id)
        id:    att_internal_gen_{md5("edge|{family}_{idx}")}
        style: colored line with direction arrows, strokeWidth=2
```

### Label Assembly Change

**Before (current):** `&#10;`-separated (newline in draw.io)

```python
# att_internal_generator.py line 269 — CURRENT
left_value = "&#10;".join(names)
```

**After:** Comma-separated

```python
# PROPOSED
left_value = ", ".join(group.labels)
```

### Dynamic Height Estimation

**Before (current):** `interface_count * line_height + padding`

```python
# att_internal_generator.py line 196 — CURRENT
def _left_height(interface_count: int) -> float:
    h = interface_count * LAYOUT["line_height"] + (2 * LAYOUT["padding"])
    return max(LAYOUT["left_min_height"], h)
```

**After:** Wrapping-aware estimate for comma-separated text in a fixed-width box.

```python
# PROPOSED — adapted from drawpyo List.autosize() pattern
# (see Section 9: Reusable Code from drawpyo-main)
def _left_height_wrapped(label_count: int, left_width: float) -> float:
    """Estimate left box height for comma-separated wrapped labels.

    Heuristic based on average label length and box width.
    Average label: ~20 chars ("APP NAME (12345), ")
    At fontSize=10, ~6.5px per char → ~30 chars per line at 180px
    → ~1.5 labels per line
    """
    if label_count == 0:
        return LAYOUT["left_min_height"]
    avg_label_chars = 20  # includes ", " separator
    chars_per_line = max(1, left_width / 6.5)
    labels_per_line = max(1, chars_per_line / avg_label_chars)
    lines = max(1, -(-label_count // int(labels_per_line)))  # ceil division
    h = lines * LAYOUT["line_height"] + 2 * LAYOUT["padding"]
    return max(LAYOUT["left_min_height"], h)
```

### Multi-Port Label

**Before:** `f"{group.port or '?'}&#10;{_direction_label(direction)}"`

**After:** `f"{group.port_display}&#10;{group.direction_display}"`

Where `port_display` is `" ".join(sorted_ports)` (e.g., `"443 8447"`).

### Connector Arrows

Unchanged logic, using the group's aggregated direction:
- `IN` → `startArrow=classic, endArrow=none` (arrow points toward the outpost)
- `OUT` → `startArrow=none, endArrow=classic` (arrow points away)
- `IN/OUT` → `startArrow=classic, endArrow=classic` (both directions)

### Connector Color

**Before:** `_protocol_color(group.protocol)` — matches raw protocol string

**After:** `group.connector_color` — from `FAMILY_COLORS[group.family]`

---

## 9. Reusable Code from drawpyo-main

All referenced files are under `C:\GitHub\aws_diag_v4_1\aws_diag_v4\docs\drawpyo-main\drawpyo-main\`. drawpyo is MIT-licensed (confirmed in `LICENSE`).

### 9.1 List.autosize() — Dynamic Height from Content

**Source:** `src/drawpyo/diagram/extended_objects.py`, lines 70-77

```python
def autosize(self) -> None:
    """Resizes the parent List to match the list items."""
    y_pos = self.startSize
    for child in self.children:
        child.geometry.y = y_pos
        y_pos = y_pos + child.height
    self.height = self.startSize + sum(child.height for child in self.children)
    self.width = min(child.width for child in self.children)
```

**What it does:** Calculates the total height of a list container by summing child item heights, then adds the header (`startSize`). It also restacks items vertically.

**How we adapt it:** Our `_left_height_wrapped()` function adapts this pattern for **text wrapping** rather than child objects. Instead of summing child heights, we estimate how many lines the comma-separated text will wrap to, then compute: `lines * line_height + padding`. The stacking concept (each row's `current_y += row_height + spacing`) is the same as the `y_pos += child.height` loop.

**Reuse type:** Pattern adaptation — the algorithm (content-driven height) is the same; the measurement unit changes from child-object count to estimated text lines.

### 9.2 Object.resize_to_children() — Container Auto-Expand

**Source:** `src/drawpyo/diagram/objects.py`, lines 606-644

```python
def resize_to_children(self) -> None:
    """Expand the size and position to fit all children."""
    for child_object in self.children:
        topmost = min(topmost, child_object.position[1] - self.autosize_margin)
        bottommost = max(bottommost,
            child_object.position[1] + child_object.height + self.autosize_margin)
        # ... leftmost, rightmost similar
    self.width = rightmost - leftmost
    self.height = bottommost - topmost
```

**What it does:** Iterates through child objects, finds the bounding box, and resizes the parent container to fit.

**How we could adapt it:** If we want the ATT Internal band container to auto-resize after generating rows (Phase 8 optional), we'd compute the bounding box of all generated rows and resize the band. This is **deferred** — currently the band keeps its template height.

**Reuse type:** Future reference — not needed for initial implementation.

### 9.3 Object.parent / xml_parent_id — Parent-Child mxCell Nesting

**Source:** `src/drawpyo/diagram/objects.py`, lines 549-553, 556-570

```python
@property
def xml_parent_id(self) -> Union[int, Any]:
    if self.parent is not None:
        return self.parent.id
    return 1

@parent.setter
def parent(self, value) -> None:
    if isinstance(value, Object):
        value.children.append(self)
        self.update_parent()
    self._parent = value
```

**What it does:** Every draw.io `mxCell` uses a `parent` attribute referencing the ID of its container. drawpyo manages this through the `parent` property which automatically updates both sides of the relationship.

**How we already use it:** `att_internal_generator.py` already sets `"parent": container_id` on every generated mxCell. This confirms the pattern is correct.

**Reuse type:** Already applied. No change needed.

### 9.4 XMLBase.xml_ify() — XML Character Escaping

**Source:** `src/drawpyo/xml_base.py`, lines 3-13, 133-144

```python
xmlize = {
    ">": "&gt;", "<": "&lt;", "&": "&amp;",
    '"': "&quot;", "'": "&apos;",
    "\n": "&#xa;", "\t": "&#x9;", "\r": "&#xd;",
}

def xml_ify(self, parameter_string: str) -> str:
    return self.translate_txt(parameter_string, xmlize)

@staticmethod
def translate_txt(string: str, replacement_dict: Dict[str, str]) -> str:
    new_str = ""
    for char in string:
        if char in replacement_dict:
            new_str = new_str + replacement_dict[char]
        else:
            new_str = new_str + char
    return new_str
```

**What it does:** Character-by-character XML escaping. Handles the standard XML special characters plus newlines/tabs.

**How we adapt it:** Our comma-separated labels may contain `&` (e.g., `"DPG - Sales & Sunrise"`). The current code uses `ET.SubElement()` which handles attribute escaping automatically via `xml.etree.ElementTree`. However, for the `value` attribute set via `cell.set("value", ...)`, ElementTree escapes `<`, `>`, and `&` but NOT newlines. The `&#10;` for newlines in the port/direction label must be manually encoded. The drawpyo `xml_ify` mapping confirms the correct escape sequences.

**Reuse type:** Reference for escape sequences — `&#10;` (newline in mxCell value) is confirmed by drawpyo's `xmlize["\n"] = "&#xa;"` (hex vs decimal representation of the same character).

### 9.5 Geometry Class — x/y/width/height Model

**Source:** `src/drawpyo/diagram/base_diagram.py`, lines 331-384

```python
class Geometry(DiagramBase):
    def __init__(self, **kwargs):
        self._x = kwargs.get("x", 0)
        self._y = kwargs.get("y", 0)
        self.width = kwargs.get("width", 120)
        self.height = kwargs.get("height", 60)
        self.as_attribute = kwargs.get("as_attribute", "geometry")

    @property
    def attributes(self):
        return {"x": self.x, "y": self.y, "width": self.width,
                "height": self.height, "as": self.as_attribute}
```

**What it does:** Typed geometry model for mxGeometry elements.

**How we already use it:** `att_internal_generator.py` creates mxGeometry sub-elements with the same attributes: `{"x": ..., "y": ..., "width": ..., "height": ..., "as": "geometry"}`. This confirms the attribute set is correct.

**Reuse type:** Already applied. No change needed.

### 9.6 style_str_from_dict() — Clean Style String Construction

**Source:** `src/drawpyo/diagram/base_diagram.py`, lines 94-123

```python
def style_str_from_dict(style_dict: Dict[str, Any]) -> str:
    if "baseStyle" in style_dict:
        style_str = [style_dict.pop("baseStyle")]
    else:
        style_str = []
    style_str = style_str + [
        "{0}={1}".format(att, style)
        for (att, style) in style_dict.items()
        if style != "" and style != None
    ]
    return ";".join(style_str)
```

**What it does:** Builds a draw.io style string from a dict, handling the baseStyle prefix correctly.

**How we could adapt it:** Our connector style in `att_internal_generator.py` currently uses `.format()` string interpolation on a template. For cleaner construction, we could use this dict-based approach. **Recommended for Phase 6** (connector color per family) to make style construction testable.

**Reuse type:** Adaptation — import the pattern (not the function) into `att_internal_generator.py`.

### 9.7 Edge Class — Arrow and Routing Patterns

**Source:** `src/drawpyo/diagram/edges.py`, lines 50-165

Key patterns:
- `line_end_target` / `line_end_source` for arrow heads
- `entryX`, `entryY`, `exitX`, `exitY` for connection point positioning
- `strokeColor`, `strokeWidth` for line styling
- `waypoints` for routing algorithm

**How it applies:** Our connector mxCell already uses `startArrow`, `endArrow`, `exitX`, `exitY`, `entryX`, `entryY`, `strokeColor`, `strokeWidth`. The drawpyo Edge class confirms these are the correct style attributes and their valid values.

**Reuse type:** Reference confirmation — already applied correctly.

### 9.8 Group Class — Bounding Box Geometry

**Source:** `src/drawpyo/diagram/objects.py`, lines 764-910

```python
class Group:
    @property
    def left(self): return min([obj.geometry.x for obj in self.objects])
    @property
    def right(self): return max([obj.geometry.x + obj.geometry.width for obj in self.objects])
    @property
    def top(self): return min([obj.geometry.y for obj in self.objects])
    @property
    def bottom(self): return max([obj.geometry.y + obj.geometry.height for obj in self.objects])
    @property
    def width(self): return self.right - self.left
    @property
    def height(self): return self.bottom - self.top
```

**What it does:** Computes bounding box geometry for a collection of objects.

**How we could adapt it:** If we want to auto-resize the ATT Internal band after generating all rows, we'd compute the bounding box of generated elements. The algorithm is: `total_height = last_row_y + last_row_height - first_row_y + margins`.

**Reuse type:** Future reference (Phase 8 optional container resize).

---

## 10. TDD Implementation Slices

Each slice is independently testable and deployable. Implement in order. Each slice follows RED-GREEN-REFACTOR.

### Slice 0: Protocol Family Normalizer — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 5
**Goal:** Create `normalize_protocol_family()` with regex-based mapping.
**Files changed:**
- `src/migration_intake/topology/interface_normalization.py` — added `PROTOCOL_FAMILY_PATTERNS`, `FAMILY_COLORS`, `normalize_protocol_family()`
- `tests/unit/topology/test_interface_normalization.py` (new) — 20 tests

**Plan deviation:** CONNECT_DIRECT regex changed from `[\s._-]?` to `[\s._:/-]?` to match the colon in "Connect:Direct" as found in real DB data.

**Validation:** `pytest tests/unit/topology/ -q` → 435 passed, 1 skipped (pre-existing). Zero regressions.

**RED tests (write first):**
```python
class TestProtocolFamilyNormalizer:
    def test_https_protocol(self):
        assert normalize_protocol_family("HTTPS(TLSv1.2)") == "HTTPS"

    def test_http_protocol(self):
        assert normalize_protocol_family("HTTP") == "HTTPS"

    def test_connect_direct(self):
        assert normalize_protocol_family("Connect:Direct Secure+ using TLS 1.2") == "CONNECT_DIRECT"

    def test_jdbc(self):
        assert normalize_protocol_family("JDBC over TLS 1.2/TCP") == "ORACLE_DB"

    def test_oracle_net(self):
        assert normalize_protocol_family("Oracle Net TCPS(TLS1.2)") == "ORACLE_DB"

    def test_oracle_native(self):
        assert normalize_protocol_family("Oracle Native Encryption(TLS1.2)") == "ORACLE_DB"

    def test_oracle_goldengate(self):
        assert normalize_protocol_family("Oracle GoldenGate secured with TLS1.2") == "ORACLE_GG"

    def test_odbc(self):
        assert normalize_protocol_family("ODBC(TCPS over TLS) TLS1.2") == "SQL_DB"

    def test_sql_server(self):
        assert normalize_protocol_family("SQL Server over TLS 1.2/TCP") == "SQL_DB"

    def test_sftp(self):
        assert normalize_protocol_family("SFTP using OpenSSH SSH-2") == "SFTP"

    def test_amqp(self):
        assert normalize_protocol_family("AMQP 1.0 over TLS 1.2") == "AMQP"

    def test_postgresql(self):
        assert normalize_protocol_family("PostgreSQL SSL/TLS(TLS1.2)") == "POSTGRESQL"

    def test_null_returns_unknown(self):
        assert normalize_protocol_family(None) == "UNKNOWN"

    def test_empty_returns_unknown(self):
        assert normalize_protocol_family("") == "UNKNOWN"

    def test_unrecognized_returns_other(self):
        assert normalize_protocol_family("FTP over TLS") == "OTHER"

    def test_case_insensitive(self):
        assert normalize_protocol_family("https(tlsv1.2)") == "HTTPS"

    def test_goldengate_matches_before_oracle(self):
        """GoldenGate must not fall through to ORACLE_DB."""
        assert normalize_protocol_family("Oracle GoldenGate TLS") == "ORACLE_GG"
```

**GREEN implementation:** The code from Section 5 above.

**Acceptance:** All 17 tests pass. Run: `python -m pytest tests/unit/topology/test_interface_normalization.py -v`

---

### Slice 1: ProtocolFamilyGroup View Model — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 7
**Goal:** Create `ProtocolFamilyGroup` dataclass with `finalize()`, `port_display`, `label_display`, `direction_display`, `sort_key`.
**Files changed:**
- `src/migration_intake/topology/interface_normalization.py` — added `_aggregate_direction()`, `ProtocolFamilyGroup` (FAMILY_COLORS already added in Slice 0)
- `tests/unit/topology/test_interface_normalization.py` — 19 new tests in `TestProtocolFamilyGroup`

**Validation:** `pytest tests/unit/topology/ -q` → 454 passed, 1 skipped. Zero regressions.

**RED tests:**
```python
class TestProtocolFamilyGroup:
    def test_single_inbound(self):
        """One inbound candidate → direction=IN, one label."""
        # Create candidate, add to group, finalize
        # Assert direction == "IN", len(labels) == 1, ports == ["443"]

    def test_mixed_direction_gives_in_out(self):
        """IN + OUT candidates → direction=IN/OUT."""

    def test_bidirectional_gives_in_out(self):
        """BIDIRECTIONAL candidate → direction=IN/OUT."""

    def test_dedup_same_app_different_ports(self):
        """Same (app, corr_id) on port 443 and 8447 → one label."""

    def test_multi_port_merged(self):
        """Candidates on ports 443 and 8447 → ports=['443', '8447']."""

    def test_ports_sorted_numerically(self):
        """Ports ['8447', '443'] → sorted as ['443', '8447']."""

    def test_labels_sorted_alphabetically(self):
        """Labels sorted by (app_acronym, correlation_id)."""

    def test_port_display_format(self):
        """port_display returns '443 8447' for multi-port group."""

    def test_label_display_comma_separated(self):
        """label_display returns 'APP1 (ID1), APP2 (ID2)'."""

    def test_unknown_direction_gives_question_mark(self):
        """All UNKNOWN direction → direction='?'."""

    def test_connector_color_from_family(self):
        """HTTPS family → '#6666FF'."""

    def test_sort_key_family_then_port(self):
        """Groups sorted by (family_name, min_port_number)."""
```

**Acceptance:** All group tests pass.

---

### Slice 2: Grouping Function — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 6
**Goal:** Implement `group_interfaces_by_protocol_family()`.
**Files changed:**
- `src/migration_intake/topology/interface_normalization.py` — added `group_interfaces_by_protocol_family()` (67-line function)
- `tests/unit/topology/test_interface_normalization.py` — 10 new tests in `TestGroupByProtocolFamily`

**Validation:** `pytest tests/unit/topology/ -q` → 464 passed, 1 skipped. Zero regressions.

**RED tests:**
```python
class TestGroupByProtocolFamily:
    def test_ccpm_like_data_produces_7_groups(self):
        """Synthetic CCPM Midrange data → 7 groups including Unknown."""

    def test_same_family_different_ports_merged(self):
        """HTTPS on 443 and HTTPS on 8447 → one HTTPS group."""

    def test_different_families_same_port_separate(self):
        """ORACLE_DB and SQL_DB both on 1433 → 2 groups."""

    def test_missing_protocol_goes_to_unknown(self):
        """Candidate with no protocol → Unknown group."""

    def test_missing_port_goes_to_unknown(self):
        """Candidate with no port → Unknown group."""

    def test_non_internal_excluded(self):
        """Azure/AWS candidates not included in INTERNAL grouping."""

    def test_empty_input_returns_empty(self):
        """No candidates → no groups."""

    def test_deterministic_ordering(self):
        """Same input in different order → same output."""

    def test_all_unknown_direction(self):
        """All candidates with unknown direction → group direction '?'."""
```

**Acceptance:** All grouping tests pass.

---

### Slice 3: Comma-Separated Labels in Generator — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 8 — Label Assembly Change
**Goal:** Change `att_internal_generator.py` to accept `ProtocolFamilyGroup` and render comma-separated labels.
**Files changed:**
- `src/migration_intake/topology/att_internal_generator.py` — added `_is_family_group()` duck-type check; refactored `generate_att_internal_rows()` to branch on group type: comma-separated labels + multi-port + aggregated direction for `ProtocolFamilyGroup`, legacy newline-separated for `InterfaceGroup`
- `tests/unit/topology/test_att_internal_generator.py` (new) — 5 tests in `TestGeneratorCommaLabels`

**RED tests:**
```python
class TestAttInternalGeneratorLabels:
    def test_comma_separated_format(self):
        """Generated left box value uses ', ' separator not '&#10;'."""

    def test_multi_port_label(self):
        """Label box shows '443 8447' for multi-port group."""

    def test_single_port_label(self):
        """Label box shows '1521' for single-port group."""

    def test_direction_in_label(self):
        """Label box second line shows 'IN/OUT' or 'IN' or 'OUT'."""

    def test_overflow_truncation(self):
        """More than max_labels_per_group → shows '(+N more)'."""
```

**Acceptance:** Generated mxCells have correct value attributes.

---

### Slice 4: Dynamic Height for Wrapped Labels — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 8 — Dynamic Height Estimation
**Drawpyo reference:** Section 9.1 — `List.autosize()` pattern
**Goal:** Add wrapping-aware `_left_height_wrapped()` alongside existing `_left_height()`.
**Files changed:**
- `src/migration_intake/topology/att_internal_generator.py` — added `_left_height_wrapped(label_count, left_width)` using chars-per-line heuristic
- `tests/unit/topology/test_att_internal_generator.py` — 4 tests in `TestDynamicHeight`

**RED tests:**
```python
class TestDynamicHeight:
    def test_single_label_min_height(self):
        """1 label → min height (60px)."""

    def test_seven_labels_taller(self):
        """7 labels at 180px width → height > min_height."""

    def test_height_scales_with_labels(self):
        """More labels → taller box."""

    def test_zero_labels_min_height(self):
        """0 labels → min height."""
```

**Acceptance:** Heights are proportional to content.

---

### Slice 5: Connector Color per Family — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 8 — Connector Color
**Drawpyo reference:** Section 9.6 — `style_str_from_dict()` pattern
**Goal:** Connector uses `group.connector_color` from `FAMILY_COLORS`.
**Files changed:**
- `src/migration_intake/topology/att_internal_generator.py` — family group path uses `group.connector_color` directly
- `tests/unit/topology/test_att_internal_generator.py` — 3 tests in `TestConnectorColors`

**Note:** Slices 3, 4, 5 were implemented together in one refactor of `generate_att_internal_rows()` since they all modify the same function. Legacy `InterfaceGroup` path preserved via duck-type branching.

**Validation:** `pytest tests/unit/topology/ -q` → 476 passed, 1 skipped. Zero regressions. All existing `InterfaceGroup` tests still pass.

**RED tests:**
```python
class TestConnectorColors:
    def test_https_family_blue(self):
        """HTTPS group → connector strokeColor=#6666FF."""

    def test_oracle_db_teal(self):
        """ORACLE_DB group → connector strokeColor=#67AB9F."""

    def test_unknown_family_gray(self):
        """UNKNOWN group → connector strokeColor=#999999."""
```

**Acceptance:** Connector colors match family map.

---

### Slice 6: Wire into Pipeline — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 3 — Data Flow
**Goal:** Replace `group_interfaces_by_protocol_port()` call with `group_interfaces_by_protocol_family()` in the extractor.
**Files changed:**
- `src/migration_intake/topology/haf_extractor.py` — imports `ProtocolFamilyGroup` and `group_interfaces_by_protocol_family`; changed `interface_groups` field type to `list[ProtocolFamilyGroup]`; changed grouping call
- `src/migration_intake/topology/haf_pipeline.py` — updated `TYPE_CHECKING` imports; updated `fill_haf_template()` and `fill_interface_regions_grouped()` type hints
- `src/migration_intake/topology/haf_service.py` — updated imports and `HafTopologyResult.interface_groups` type to `list[ProtocolFamilyGroup]`
- `tests/unit/topology/test_haf_extractor.py` — updated `test_interface_groups_created_for_internal` to not assume `.protocol`; added `test_interface_groups_are_protocol_family_type`

**Validation:** `pytest tests/unit/topology/ -q` → 477 passed, 1 skipped. Zero regressions. All existing pipeline and extractor tests pass.

**RED tests:**
```python
class TestPipelineWithFamilyGroups:
    def test_full_pipeline_produces_family_groups(self):
        """fill_haf_template with family groups → valid XML with comma labels."""

    def test_non_internal_regions_unchanged(self):
        """Azure and tier2 slots still filled by legacy path."""

    def test_extraction_returns_family_groups(self):
        """extract_haf_data returns ProtocolFamilyGroup objects."""
```

**Acceptance:** Full pipeline produces correct output; Azure/AWS unaffected.

---

### Slice 7: Unknown Group Rendering — COMPLETE

**Status:** COMPLETE
**Plan reference:** Section 6 — Unknown group for incomplete records
**Goal:** Ensure incomplete records appear in a visible Unknown group.
**Files changed:**
- `tests/unit/topology/test_att_internal_generator.py` — 4 new tests in `TestUnknownGroupRendering`
- No production code changes needed — Unknown group was already handled by Slice 2 (grouping) and Slice 3 (rendering)

**Note:** 9 existing tests from Slices 0-2 already covered Unknown at the normalization/grouping level. Slice 7 adds generator-level rendering tests.

**Validation:** `pytest tests/unit/topology/ -q` → 481 passed, 1 skipped. Zero regressions.

**RED tests:**
```python
class TestUnknownGroup:
    def test_missing_protocol_in_unknown_group(self):
        """Interface with no protocol → Unknown group."""

    def test_missing_port_in_unknown_group(self):
        """Interface with no port → Unknown group."""

    def test_unknown_group_rendered_last(self):
        """Unknown group appears after all other groups."""

    def test_unknown_group_shows_question_marks(self):
        """Unknown group label shows '?' for port and direction."""
```

**Acceptance:** Incomplete records visible at bottom.

---

### Slice 8: E2E Validation and Hardening — COMPLETE

**Status:** COMPLETE
**Plan reference:** All sections
**Goal:** Full validation with real template, determinism check, visual verification.
**Files changed:**
- `tests/unit/topology/test_haf_e2e.py` — un-skipped and updated `test_structural_integrity_preserved` (accounts for static slot removal + generated cell addition); added `test_generated_cells_use_comma_labels` and `test_interface_groups_are_family_type`
- `STATE.md` — updated with final implementation state

**Steps:**
1. Run `python -m pytest tests/unit/topology/ -v` — all pass
2. Run `python -m pytest tests/ -v` — no regressions
3. Verify deterministic output (same inputs → same bytes)
4. Deploy locally, generate CCPM topology, open in draw.io, visual check
5. Update `STATE.md`

**Acceptance criteria:** See Section 13.

---

## 11. Test Plan

### Summary

| Category | Test Count | Files |
|---|---|---|
| Protocol family normalizer | 17 | `test_interface_normalization.py` |
| ProtocolFamilyGroup view model | 12 | `test_interface_normalization.py` |
| Grouping function | 9 | `test_interface_normalization.py` |
| Generator labels/format | 5 | `test_att_internal_generator.py` |
| Dynamic height | 4 | `test_att_internal_generator.py` |
| Connector colors | 3 | `test_att_internal_generator.py` |
| Pipeline wiring | 3 | `test_haf_pipeline.py`, `test_haf_extractor.py` |
| Unknown group | 4 | `test_interface_normalization.py`, `test_att_internal_generator.py` |
| E2E | 4 | `test_haf_e2e.py` |
| **Total** | **~61** | |

### Edge Cases Covered

- Null/empty/whitespace protocol and port
- Case variations in protocol strings
- GoldenGate matching before generic Oracle
- Same app on multiple ports (dedup)
- Same port with different protocol families (separate groups)
- Mixed IN+OUT → IN/OUT direction
- BIDIRECTIONAL entries
- All-UNKNOWN directions
- Missing acronym or correlation ID
- Large groups (20+ labels) → truncation
- Deterministic ordering across repeated runs
- No impact on Azure/AWS/Tier2 sections

---

## 12. Risks and Open Questions

### Risks

| ID | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | New protocols in future data won't match any family | Medium | Fallback to `"OTHER"` family; log unmatched; easy to add one regex line |
| R2 | Wrapped text height estimate is approximate | Low | Conservative heuristic; visual validation in Phase 8; LAYOUT config tunable |
| R3 | Static slot removal changes template structure | Medium | Already idempotent; `_delete_generated()` + `_remove_static_slots()` tested |
| R4 | Connector routing may overlap with fewer, taller rows | Low | Explicit source/target waypoints; validate in draw.io |
| R5 | `InterfaceGroup` used elsewhere → breaking change | Medium | **Keep `InterfaceGroup` and `group_interfaces_by_protocol_port()`** — add new types alongside |

### Open Questions

| ID | Question | Impact | Blocking? |
|---|---|---|---|
| Q1 | Should ORACLE_DB (JDBC/Net) and ORACLE_GG (GoldenGate) merge? | Whether port 1521 and 7809 are one row | No — proposed separate |
| Q2 | Should the band container auto-resize height? | Layout aesthetics | No — defer to visual review |
| Q3 | Should protocol family normalizer be JSON-configurable? | Maintainability | No — hardcoded; easy to refactor later |
| Q4 | Can the same app label appear in MULTIPLE family groups? | Dedup scope | No — dedup is per-group only |

---

## 13. Acceptance Criteria

### Functional

1. **AC-1:** INTERNAL interfaces are grouped by protocol family. Each family = one row.
2. **AC-2:** Multiple ports within one family are merged. Port label shows all ports (e.g., `"443 8447"`).
3. **AC-3:** Direction is aggregated: all-IN → `"IN"`, all-OUT → `"OUT"`, mixed → `"IN/OUT"`.
4. **AC-4:** Labels are comma-separated: `"APP1 (ID1), APP2 (ID2)"`.
5. **AC-5:** Duplicate `(app_acronym, correlation_id)` pairs are deduplicated within each group.
6. **AC-6:** Labels sorted alphabetically by `(app_acronym, correlation_id)`.
7. **AC-7:** Ports sorted numerically within each label.
8. **AC-8:** Incomplete records (missing protocol/port) appear in Unknown group at bottom.
9. **AC-9:** Connector color matches protocol family per `FAMILY_COLORS` map.
10. **AC-10:** Protocol is NOT displayed in the port/direction box.

### Non-Functional

11. **AC-11:** Same inputs produce byte-identical output (determinism).
12. **AC-12:** Azure, AWS, Tier2 sections unaffected.
13. **AC-13:** Protected cells (legend, frame) never mutated.
14. **AC-14:** All tests use synthetic data (no client data).
15. **AC-15:** Existing test suite passes with zero regressions.
16. **AC-16:** Protocol family mapping is documented and easy to extend.

### Visual (Manual Validation)

17. **AC-17:** For CCPM, AT&T Internal section produces ~7 group rows (down from ~12).
18. **AC-18:** Box heights proportional to content (no clipping).
19. **AC-19:** Layout matches Screenshot 2's structure.

---

## 14. File Change Summary

| File | Action | Slices |
|---|---|---|
| `src/migration_intake/topology/interface_normalization.py` | ADD: `PROTOCOL_FAMILY_PATTERNS`, `normalize_protocol_family()`, `FAMILY_COLORS`, `ProtocolFamilyGroup`, `_aggregate_direction()`, `group_interfaces_by_protocol_family()` | 0, 1, 2 |
| `src/migration_intake/topology/att_internal_generator.py` | MODIFY: `generate_att_internal_rows()` to accept `ProtocolFamilyGroup`, comma labels, dynamic height, multi-port label, family colors | 3, 4, 5 |
| `src/migration_intake/topology/haf_extractor.py` | MODIFY: call `group_interfaces_by_protocol_family()` instead of `group_interfaces_by_protocol_port()` | 6 |
| `src/migration_intake/topology/haf_pipeline.py` | MODIFY: update type hint for `interface_groups` parameter | 6 |
| `src/migration_intake/topology/haf_service.py` | MODIFY: pass-through type update if needed | 6 |
| `tests/unit/topology/test_interface_normalization.py` | CREATE: ~38 tests for normalizer, view model, grouping | 0, 1, 2, 7 |
| `tests/unit/topology/test_att_internal_generator.py` | CREATE: ~12 tests for labels, height, colors | 3, 4, 5, 7 |
| `tests/unit/topology/test_haf_pipeline.py` | MODIFY: update grouped rendering tests | 6 |
| `tests/unit/topology/test_haf_extractor.py` | MODIFY: update extraction tests | 6 |
| `tests/unit/topology/test_haf_e2e.py` | MODIFY: update/add E2E tests | 8 |
| `STATE.md` | MODIFY: update implementation state | 8 |

### Files NOT Changed (preserved)

- `outpost_v1.json` profile — no changes needed
- `guide_policy.py` — read-only reference
- `haf_styles.py` — unrelated to this change
- All Azure/AWS/Tier2 rendering paths
- All protected roles and legend cells
