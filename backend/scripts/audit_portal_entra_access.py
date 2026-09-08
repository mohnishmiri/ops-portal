#!/usr/bin/env python
"""Audit — and optionally repair — Entra assignments for the Ops Portal app.

Background
----------
Portal access comes from Entra groups assigned to the ``OpsPortal.Read`` /
``OpsPortal.Write`` / ``OpsPortal.Admin`` app roles.  Two tenant-side
misconfigurations let an unentitled user sign in anyway:

1. ``appRoleAssignmentRequired = false`` on the Enterprise Application, so
   Azure AD issues a token to any authenticated tenant user.
2. Users assigned to the app directly under **"Default Access"** (appRoleId
   ``00000000-0000-0000-0000-000000000000``).  They are assigned but hold no
   app role, so their token carries no ``roles`` claim and the portal denies
   them *after* a successful login — the "logs in but no page works" report.

The trap worth knowing: turning on "Assignment required" does **not** fix (2).
Those users *are* assigned, merely role-less, so Azure still lets them through.
The Default Access rows have to be removed as well.

Removing a Default Access row is only safe when that user already receives a
role through one of the assigned groups.  Otherwise it is a hard lockout.  So
this script establishes coverage first and refuses to remove anything it cannot
prove is covered.

Usage
-----
Audit only — read-only, safe to run any time::

    az login    # as an admin-consented user, NOT the portal's own SP
    uv run python scripts/audit_portal_entra_access.py

Repair — each step reports unless you add ``--yes``::

    uv run python scripts/audit_portal_entra_access.py --remove-default-access --yes
    uv run python scripts/audit_portal_entra_access.py --require-assignment --yes

Resolving group membership needs ``Group.Read.All`` or ``Directory.Read.All``.
The portal's own service principal is denied that, so sign in as a directory
reader; otherwise coverage comes back UNKNOWN and no removal is permitted.

Override the target app with ``OPS_PORTAL_APP_ID`` if it ever changes.
"""

import argparse
import json
import os
import subprocess
import sys

GRAPH = "https://graph.microsoft.com/v1.0"

# The "Default Access" pseudo-role: assigned to the app, holding no app role.
DEFAULT_ACCESS_ROLE_ID = "00000000-0000-0000-0000-000000000000"

DEFAULT_APP_ID = "68a52619-4061-448c-8264-922aedba1b5b"


# ── Graph plumbing ────────────────────────────────────────────────────────────


def _az(args: list[str]) -> str:
    """Run an ``az`` command, returning stdout and raising on failure."""
    result = subprocess.run(["az", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def graph_get(url: str) -> dict:
    """GET a Graph URL, following ``@odata.nextLink`` to completion.

    Paging matters here: ``transitiveMembers`` on a large group and
    ``appRoleAssignedTo`` on a busy app both exceed one page, and a partial
    read would silently understate coverage — which is exactly the direction
    that turns a "safe to remove" verdict into a lockout.
    """
    collected: list[dict] = []
    payload: dict = {}
    while url:
        payload = json.loads(_az(["rest", "--method", "GET", "--url", url]) or "{}")
        if "value" not in payload:
            return payload
        collected.extend(payload["value"])
        url = payload.get("@odata.nextLink", "")
    return {"value": collected}


def graph_write(method: str, url: str, body: dict | None = None) -> None:
    """Issue a mutating Graph call."""
    args = ["rest", "--method", method, "--url", url]
    if body is not None:
        args += [
            "--headers",
            "Content-Type=application/json",
            "--body",
            json.dumps(body),
        ]
    _az(args)


# ── Reads ─────────────────────────────────────────────────────────────────────


def load_service_principal(app_id: str) -> dict:
    """Fetch the Enterprise Application's SP by client (app) ID."""
    sp = graph_get(
        f"{GRAPH}/servicePrincipals(appId='{app_id}')?$select=id,displayName,appId,appRoles,appRoleAssignmentRequired"
    )
    if not sp.get("id"):
        raise RuntimeError(f"No service principal found for appId {app_id}")
    return sp


def group_member_ids(group_id: str) -> set[str] | None:
    """Transitive *user* member IDs of a group, or None if unreadable.

    None is a distinct outcome from the empty set: "we are not allowed to look"
    must never be mistaken for "the group is empty", or every user would look
    uncovered and removal would lock out the whole portal.
    """
    try:
        page = graph_get(f"{GRAPH}/groups/{group_id}/transitiveMembers/microsoft.graph.user?$select=id,displayName")
    except RuntimeError as exc:
        if "Authorization_RequestDenied" in str(exc) or "Forbidden" in str(exc):
            return None
        raise
    return {m["id"] for m in page.get("value", []) if m.get("id")}


# ── Audit ─────────────────────────────────────────────────────────────────────


def audit(sp: dict) -> dict:
    """Classify every assignment and work out who Default Access can lose.

    Returns the assignment split plus, for each role-less user, whether a group
    already grants them a role.
    """
    role_names = {r["id"]: r["value"] for r in sp.get("appRoles", [])}
    assignments = graph_get(f"{GRAPH}/servicePrincipals/{sp['id']}/appRoleAssignedTo").get("value", [])

    group_rows = [a for a in assignments if a.get("principalType") == "Group"]
    role_less = [
        a for a in assignments if a.get("principalType") == "User" and a.get("appRoleId") == DEFAULT_ACCESS_ROLE_ID
    ]
    roled = [
        a for a in assignments if a.get("appRoleId") != DEFAULT_ACCESS_ROLE_ID and a.get("principalType") == "User"
    ]

    # Which role each group confers, and who is in it.
    coverage: dict[str, str] = {}
    unreadable: list[str] = []
    for g in group_rows:
        members = group_member_ids(g["principalId"])
        if members is None:
            unreadable.append(g.get("principalDisplayName", g["principalId"]))
            continue
        granted = role_names.get(g.get("appRoleId", ""), g.get("appRoleId", "?"))
        for uid in members:
            # A user in both Read and Write groups keeps the first seen; the
            # portal unions roles at token time, so this label is indicative.
            coverage.setdefault(uid, granted)

    return {
        "role_names": role_names,
        "groups": group_rows,
        "role_less": role_less,
        "roled": roled,
        "coverage": coverage,
        "unreadable_groups": unreadable,
        "total": len(assignments),
    }


def print_report(sp: dict, report: dict) -> None:
    """Print the audit as a reviewable table."""
    print(f"App          : {sp.get('displayName')}  ({sp.get('appId')})")
    print(f"ServicePrinc.: {sp['id']}")
    required = sp.get("appRoleAssignmentRequired", False)
    flag = "OK" if required else "GAP — any tenant user can obtain a token"
    print(f"Assignment required: {required}   <- {flag}")
    print(f"Total assignments  : {report['total']}")
    print()

    print("Groups assigned to app roles")
    print("-" * 78)
    if not report["groups"]:
        print("  (none — group-based access is not configured)")
    for g in report["groups"]:
        role = report["role_names"].get(g.get("appRoleId", ""), "?")
        print(f"  {g.get('principalDisplayName'):45s} -> {role}")
    print()

    if report["roled"]:
        print("Users with a direct app role (left untouched)")
        print("-" * 78)
        for a in report["roled"]:
            role = report["role_names"].get(a.get("appRoleId", ""), "?")
            print(f"  {a.get('principalDisplayName'):45s} -> {role}")
        print()

    print('Users assigned "Default Access" — no app role, cannot use the portal')
    print("-" * 78)
    if not report["role_less"]:
        print("  (none — nothing to clean up)")
        return

    if report["unreadable_groups"]:
        print("  Group membership unreadable for: " + ", ".join(report["unreadable_groups"]))
        print("  Coverage cannot be proven, so every verdict below is UNKNOWN.")
        print("  Re-run as a directory reader (Group.Read.All/Directory.Read.All).")
        print()

    for i, a in enumerate(report["role_less"], start=1):
        name = a.get("principalDisplayName", "?")
        if report["unreadable_groups"]:
            verdict = "UNKNOWN — cannot verify"
        elif a["principalId"] in report["coverage"]:
            verdict = f"SAFE to remove (group grants {report['coverage'][a['principalId']]})"
        else:
            verdict = "WOULD LOCK OUT — add to a group first"
        print(f"  {i:2d}. {name:45s} {verdict}")


def removable(report: dict) -> list[dict]:
    """Default Access rows whose users are provably covered by a group."""
    if report["unreadable_groups"]:
        return []
    return [a for a in report["role_less"] if a["principalId"] in report["coverage"]]


# ── Repairs ───────────────────────────────────────────────────────────────────


def remove_default_access(sp: dict, report: dict, apply: bool) -> int:
    """Drop Default Access rows for users a group already covers.

    Users with no group coverage are deliberately skipped: removing them would
    revoke the only thing tying them to the app.  Get them into a group first,
    then re-run.
    """
    safe = removable(report)
    blocked = [a for a in report["role_less"] if a not in safe]

    print()
    print("=" * 78)
    print("REMOVE DEFAULT ACCESS")
    print("=" * 78)

    if report["unreadable_groups"]:
        print("Refusing to remove anything: group membership was unreadable, so")
        print("coverage cannot be proven. Re-run as a directory reader.")
        return 1

    if not safe:
        print("Nothing is safe to remove.")
        if blocked:
            print(f"{len(blocked)} user(s) hold Default Access but no group role.")
            print("Add them to AP-31599-ATTCC-Ops-Portal-Read/-Write, then re-run.")
        return 0

    for a in safe:
        name = a.get("principalDisplayName", "?")
        if not apply:
            print(f"  [dry-run] would remove Default Access from {name}")
            continue
        graph_write(
            "DELETE",
            f"{GRAPH}/servicePrincipals/{sp['id']}/appRoleAssignedTo/{a['id']}",
        )
        print(f"  removed Default Access from {name}")
        # Printed so a mistake is reversible without reconstructing the payload.
        rollback = json.dumps(
            {
                "principalId": a["principalId"],
                "resourceId": sp["id"],
                "appRoleId": DEFAULT_ACCESS_ROLE_ID,
            }
        )
        print(
            f"      rollback: az rest --method POST --url "
            f"{GRAPH}/servicePrincipals/{sp['id']}/appRoleAssignedTo "
            f"--headers Content-Type=application/json --body '{rollback}'"
        )

    if blocked:
        print()
        print(f"Skipped {len(blocked)} user(s) with no group coverage:")
        for a in blocked:
            print(f"  - {a.get('principalDisplayName')}")

    if not apply:
        print()
        print("Dry run only. Re-run with --yes to apply.")
    return 0


def require_assignment(sp: dict, apply: bool) -> int:
    """Set ``appRoleAssignmentRequired`` so unassigned users cannot get a token."""
    print()
    print("=" * 78)
    print("REQUIRE ASSIGNMENT")
    print("=" * 78)

    if sp.get("appRoleAssignmentRequired"):
        print("Already enabled — nothing to do.")
        return 0

    if not apply:
        print("[dry-run] would set appRoleAssignmentRequired = true")
        print("Unassigned tenant users would then be refused a token by Azure AD,")
        print("before the portal is ever reached. Re-run with --yes to apply.")
        return 0

    graph_write(
        "PATCH",
        f"{GRAPH}/servicePrincipals/{sp['id']}",
        {"appRoleAssignmentRequired": True},
    )
    print("appRoleAssignmentRequired = true")
    print(
        "Rollback: az rest --method PATCH --url "
        f"{GRAPH}/servicePrincipals/{sp['id']} "
        "--headers Content-Type=application/json "
        "--body '{\"appRoleAssignmentRequired\": false}'"
    )
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and repair Entra assignments for the Ops Portal app.",
        epilog="With no flags the script only audits and changes nothing.",
    )
    parser.add_argument(
        "--remove-default-access",
        action="store_true",
        help="drop Default Access rows for users already covered by a group",
    )
    parser.add_argument(
        "--require-assignment",
        action="store_true",
        help="set appRoleAssignmentRequired = true on the Enterprise App",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="actually apply the selected repairs (otherwise dry-run)",
    )
    args = parser.parse_args()

    app_id = os.environ.get("OPS_PORTAL_APP_ID", DEFAULT_APP_ID)

    try:
        sp = load_service_principal(app_id)
        report = audit(sp)
    except RuntimeError as exc:
        print(f"Graph read failed: {exc}", file=sys.stderr)
        print("Run 'az login' as an admin-consented directory reader.", file=sys.stderr)
        return 1

    print_report(sp, report)

    status = 0
    try:
        if args.remove_default_access:
            status |= remove_default_access(sp, report, apply=args.yes)
        if args.require_assignment:
            status |= require_assignment(sp, apply=args.yes)
    except RuntimeError as exc:
        print(f"\nRepair failed: {exc}", file=sys.stderr)
        return 1

    if not (args.remove_default_access or args.require_assignment):
        print()
        print("Audit only. Repairs available:")
        print("  --remove-default-access   drop provably-covered Default Access rows")
        print("  --require-assignment      block unassigned users at Azure AD")
        print("Add --yes to apply; both are dry-run without it.")

    return status


if __name__ == "__main__":
    sys.exit(main())
