"""
Topology gap report generator — based on spike report.py design.

This module generates HTML gap reports documenting:
- Generation status and summary
- Source/output inventories
- Issues and gaps
- Mutations made to the diagram

Design rules:
- Self-contained HTML with no external dependencies
- Script-free with restrictive CSP
- All evidence content is escaped
- Provides human-readable issue list
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ReportIssue:
    """An issue to include in the gap report."""

    issue_id: str
    issue_type: str  # MISSING, CONFLICT, UNVERIFIED, INVALID
    severity: str  # BLOCKER, CRITICAL, HIGH, MEDIUM, LOW, INFO
    status: str  # OPEN, RESOLVED, PERMITTED
    message: str
    related_paths: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    resolution: dict[str, Any] | None = None
    owner: str | None = None
    action_required: str | None = None


@dataclass
class ReportData:
    """Data for generating a gap report."""

    app_id: str
    app_name: str
    run_id: str
    run_status: str  # READY_FOR_REVIEW, GENERATED_WITH_GAPS
    generated_at: datetime

    # Input references
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    base_diagram_name: str | None = None
    base_diagram_hash: str | None = None

    # Output references
    output_diagram_name: str | None = None
    output_diagram_hash: str | None = None

    # Issues and mutations
    issues: list[ReportIssue] = field(default_factory=list)
    mutations: list[dict[str, Any]] = field(default_factory=list)

    # Tokens used
    tokens: dict[str, str] = field(default_factory=dict)


def generate_gap_report(data: ReportData) -> bytes:
    """
    Generate an HTML gap report.
    
    Args:
        data: The report data
        
    Returns:
        HTML report as bytes
    """
    # Count issues by severity
    blockers = [i for i in data.issues if i.severity == "BLOCKER"]
    criticals = [i for i in data.issues if i.severity == "CRITICAL"]
    highs = [i for i in data.issues if i.severity == "HIGH"]
    mediums = [i for i in data.issues if i.severity == "MEDIUM"]
    lows = [i for i in data.issues if i.severity in ("LOW", "INFO")]

    # Determine status color
    if data.run_status == "READY_FOR_REVIEW":
        status_color = "#16a34a"
        status_bg = "#e4f4ea"
    else:
        status_color = "#d97706"
        status_bg = "#fff1d6"

    # Build issues HTML
    issues_html = ""
    if data.issues:
        issues_html = _build_issues_section(data.issues)
    else:
        issues_html = """
        <div class="card">
            <p class="success">No issues detected.</p>
        </div>
        """

    # Build mutations HTML
    mutations_html = ""
    if data.mutations:
        mutations_html = _build_mutations_section(data.mutations)

    # Build tokens HTML
    tokens_html = ""
    if data.tokens:
        tokens_html = _build_tokens_section(data.tokens)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
    <title>Topology Gap Report - {html.escape(data.app_name)}</title>
    <style>
        :root {{
            --color-navy: #061733;
            --color-cyan: #0891b2;
            --color-success: #16a34a;
            --color-success-bg: #e4f4ea;
            --color-warning: #d97706;
            --color-warning-bg: #fff1d6;
            --color-danger: #dc2626;
            --color-danger-bg: #fde8e9;
            --color-border: #d1dde3;
            --color-text: #16202a;
            --color-text-muted: #687783;
            --color-surface: #ffffff;
            --color-canvas: #edf5f7;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            color: var(--color-text);
            background: var(--color-canvas);
            padding: 2rem;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        
        h1 {{
            color: var(--color-navy);
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
        }}
        
        h2 {{
            color: var(--color-navy);
            font-size: 1.125rem;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--color-border);
        }}
        
        h3 {{
            font-size: 1rem;
            margin-bottom: 0.5rem;
        }}
        
        .card {{
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 2rem;
        }}
        
        .status-badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            color: {status_color};
            background: {status_bg};
        }}
        
        .meta {{
            color: var(--color-text-muted);
            font-size: 0.875rem;
        }}
        
        .meta code {{
            font-family: 'Cascadia Code', monospace;
            font-size: 0.75rem;
            background: var(--color-canvas);
            padding: 2px 4px;
            border-radius: 4px;
        }}
        
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        
        .summary-item {{
            text-align: center;
            padding: 1rem;
            background: var(--color-canvas);
            border-radius: 8px;
        }}
        
        .summary-item .count {{
            font-size: 1.5rem;
            font-weight: 700;
        }}
        
        .summary-item .label {{
            font-size: 0.75rem;
            color: var(--color-text-muted);
            text-transform: uppercase;
        }}
        
        .summary-item.blocker .count {{ color: var(--color-danger); }}
        .summary-item.critical .count {{ color: var(--color-danger); }}
        .summary-item.high .count {{ color: var(--color-warning); }}
        .summary-item.medium .count {{ color: var(--color-warning); }}
        .summary-item.low .count {{ color: var(--color-text-muted); }}
        
        .issue {{
            padding: 1rem;
            border: 1px solid var(--color-border);
            border-radius: 8px;
            margin-bottom: 1rem;
        }}
        
        .issue.blocker {{ border-left: 4px solid var(--color-danger); }}
        .issue.critical {{ border-left: 4px solid var(--color-danger); }}
        .issue.high {{ border-left: 4px solid var(--color-warning); }}
        .issue.medium {{ border-left: 4px solid var(--color-warning); }}
        
        .issue-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        
        .issue-type {{
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--color-text-muted);
        }}
        
        .severity-badge {{
            font-size: 0.625rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
        }}
        
        .severity-badge.blocker {{ background: var(--color-danger-bg); color: var(--color-danger); }}
        .severity-badge.critical {{ background: var(--color-danger-bg); color: var(--color-danger); }}
        .severity-badge.high {{ background: var(--color-warning-bg); color: var(--color-warning); }}
        .severity-badge.medium {{ background: var(--color-warning-bg); color: var(--color-warning); }}
        .severity-badge.low {{ background: var(--color-canvas); color: var(--color-text-muted); }}
        
        .success {{
            color: var(--color-success);
        }}
        
        dl {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.5rem 1rem;
        }}
        
        dt {{
            color: var(--color-text-muted);
            font-size: 0.875rem;
        }}
        
        dd {{
            font-size: 0.875rem;
            word-break: break-all;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }}
        
        th, td {{
            padding: 0.5rem;
            text-align: left;
            border-bottom: 1px solid var(--color-border);
        }}
        
        th {{
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--color-text-muted);
            background: var(--color-canvas);
        }}
        
        .footer {{
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid var(--color-border);
            color: var(--color-text-muted);
            font-size: 0.75rem;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div>
                <h1>Topology Gap Report</h1>
                <p class="meta">{html.escape(data.app_name)} ({html.escape(data.app_id)})</p>
            </div>
            <span class="status-badge">{html.escape(data.run_status.replace('_', ' '))}</span>
        </header>
        
        <div class="card">
            <h2>Generation Summary</h2>
            <div class="summary-grid">
                <div class="summary-item blocker">
                    <div class="count">{len(blockers)}</div>
                    <div class="label">Blockers</div>
                </div>
                <div class="summary-item critical">
                    <div class="count">{len(criticals)}</div>
                    <div class="label">Critical</div>
                </div>
                <div class="summary-item high">
                    <div class="count">{len(highs)}</div>
                    <div class="label">High</div>
                </div>
                <div class="summary-item medium">
                    <div class="count">{len(mediums)}</div>
                    <div class="label">Medium</div>
                </div>
                <div class="summary-item low">
                    <div class="count">{len(lows)}</div>
                    <div class="label">Low/Info</div>
                </div>
            </div>
            
            <dl>
                <dt>Run ID</dt>
                <dd><code>{html.escape(data.run_id)}</code></dd>
                <dt>Generated</dt>
                <dd>{data.generated_at.isoformat()}</dd>
                {f'<dt>Snapshot ID</dt><dd><code>{html.escape(data.snapshot_id or "N/A")}</code></dd>' if data.snapshot_id else ''}
                {f'<dt>Snapshot Hash</dt><dd><code>{html.escape((data.snapshot_hash or "")[:32])}...</code></dd>' if data.snapshot_hash else ''}
                {f'<dt>Base Diagram</dt><dd>{html.escape(data.base_diagram_name or "N/A")}</dd>' if data.base_diagram_name else ''}
            </dl>
        </div>
        
        <div class="card">
            <h2>Issues ({len(data.issues)})</h2>
            {issues_html}
        </div>
        
        {mutations_html}
        
        {tokens_html}
        
        <footer class="footer">
            Generated by Migration Intake Topology Generator<br>
            Report generated: {datetime.now(tz=UTC).isoformat()}
        </footer>
    </div>
</body>
</html>"""

    return html_content.encode("utf-8")


def _build_issues_section(issues: list[ReportIssue]) -> str:
    """Build the issues section HTML."""
    html_parts = []

    for issue in issues:
        severity_class = issue.severity.lower()

        html_parts.append(f"""
        <div class="issue {severity_class}">
            <div class="issue-header">
                <span class="issue-type">{html.escape(issue.issue_type)}</span>
                <span class="severity-badge {severity_class}">{html.escape(issue.severity)}</span>
            </div>
            <p><strong>{html.escape(issue.message)}</strong></p>
            {f'<p class="meta">Related: {html.escape(", ".join(issue.related_paths))}</p>' if issue.related_paths else ''}
            {f'<p class="meta">Owner: {html.escape(issue.owner)}</p>' if issue.owner else ''}
            {f'<p class="meta">Action: {html.escape(issue.action_required)}</p>' if issue.action_required else ''}
        </div>
        """)

    return "\n".join(html_parts)


def _build_mutations_section(mutations: list[dict[str, Any]]) -> str:
    """Build the mutations section HTML."""
    rows = []
    for m in mutations:
        rows.append(f"""
        <tr>
            <td>{html.escape(str(m.get('slot_name', '')))}</td>
            <td><code>{html.escape(str(m.get('cell_id', '')))}</code></td>
            <td>{html.escape(str(m.get('original_value', ''))[:50])}</td>
            <td>{html.escape(str(m.get('new_value', ''))[:50])}</td>
        </tr>
        """)

    return f"""
    <div class="card">
        <h2>Diagram Mutations ({len(mutations)})</h2>
        <table>
            <thead>
                <tr>
                    <th>Slot</th>
                    <th>Cell ID</th>
                    <th>Original</th>
                    <th>New Value</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _build_tokens_section(tokens: dict[str, str]) -> str:
    """Build the tokens section HTML."""
    rows = []
    for name, value in sorted(tokens.items()):
        rows.append(f"""
        <tr>
            <td><code>{html.escape(name)}</code></td>
            <td>{html.escape(str(value))}</td>
        </tr>
        """)

    return f"""
    <div class="card">
        <h2>Token Values ({len(tokens)})</h2>
        <table>
            <thead>
                <tr>
                    <th>Token</th>
                    <th>Value</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """
