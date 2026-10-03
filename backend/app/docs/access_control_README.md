# Access Control & Subscription Scoping — Implementation Guide

For engineers changing backend routes or services. The security-level model
is in `docs/access-control-design.md`; the project model, go-live and
onboarding steps are in `docs/PROJECT_ACCESS.md`.

## Overview

Two dimensions, both enforced server-side:

1. **What** — Entra app role → `UserContext.roles`
   (`SUPER_ADMIN` ⊃ `ADMIN` ⊃ `WRITE` ⊃ `READ`), plus module/page/capability
   `Permission` rows.
2. **Where** — project / app / subscription **grants** → the subscriptions a
   user may read and write (`AccessScope`).

Router dependencies on `api_router`, in order (`app/api/v1/router.py`):

```
enforce_portal_access → enforce_module_access → bind_subscription_scope → enforce_target_access
```

## Models

| Model | Purpose |
|-------|---------|
| `Resource` / `Permission` | Module, page and capability (`operation`) grants to a user, role or team |
| `Project` | Business portfolio, e.g. Commissions, BDS |
| `ProjectApp` | App in a project; `app_code` is the AppID in subscription names |
| `AdminSubscription` | Subscription registry (`enabled`, `monitored`), plus placement: `app_id`, `tier` (`prod`/`nonprod`; null counts as prod) |
| `ProjectAdmin` | Assigns an Entra-Admin user to administer a project |
| `AccessGrant` | `subject_type` user/everyone × `scope_type` project/app/subscription × `tier` × `level` read/write |
| `AccessRequest` / `AccessRequestItem` | Access requests, decided line by line |
| `PortalUser` | Users seen at sign-in; the list admins grant to |
| `UserSubscriptionPreference` | Per-user picker selection (JSON) |

## Resolving the scope

| Component | Location | Role |
|-----------|----------|------|
| `compute_access_scope()` / `resolve_access_scope()` | `app/core/access_scope.py` | Grants + project admins → `AccessScope(readable, writable, admin_project_ids, unrestricted)`. Memoized per request. Fails closed (503) if the DB is unavailable, except for Super Admins. |
| `load_topology()` | `app/core/access_scope.py` | Subscription → app → project → tier, cached 30 s per process. Call `invalidate_access_topology()` after any placement change. |
| `bind_subscription_scope` | `app/core/subscription_scope.py` | Effective scope = monitored ∩ readable ∩ picker selection. Binds the scope to context vars. 403 on module routes when nothing is readable. |
| `get_scoped_subscription_ids()` | `app/core/subscription_scope.py` | Services call this for HTTP reads |
| `get_monitored_subscription_ids()` | `app/core/subscription_resolver.py` | Background jobs only (no user scope) |
| `scope_is_full()` | `app/core/subscription_scope.py` | Serve portal-wide snapshots only when true |
| `enforce_target_access` | `app/core/target_access.py` | Checks subscriptions named anywhere in path, query or JSON body: ARM IDs, `subscription_id`-like keys, Key Vault URIs/names (resolved via `kv_vaults`). Read for GET and `route_policy.READ_PERMITTED_MUTATIONS`; write otherwise. |
| `assert_resource_access()` / `arm_scope_clause()` / `subscription_scope_clause()` | `app/core/access_scope.py` | Row-level checks and SQL filters for records loaded by database ID |

Rules worth knowing:
- An **empty readable set means "nothing"**, never "all". Do not populate or
  rely on `UserContext.allowed_subscriptions`; its "empty = all" meaning is
  unsafe.
- The `subscription_ids` query parameter is a view filter. It is narrowed to
  what the user may see, never rejected, and is not treated as a target.
- With no request in progress (scheduler, startup sync), `current_access_scope()`
  is `None` and the row helpers do not check anything.

## Endpoints

- `GET /api/v1/auth/session` — includes `is_super_admin` and `access`
  (`has_subscription_access`, `admin_project_ids`, counts); records the
  sign-in.
- `GET/PUT /api/v1/auth/subscription-scope`,
  `GET /api/v1/auth/available-subscriptions` — the picker, limited to
  readable subscriptions, with project/app/tier per entry.
- `/api/v1/access/*` — my access, catalog, submit/cancel requests (any user).
- `/api/v1/access/admin/*` — projects, apps, placements, project admins,
  users, grants, request decisions. Requires the Admin role; the service
  limits Project Admins to their own projects.
- `/api/v1/admin/*`, `/api/v1/permissions/*` — **Super Admin only**.

## Adding or changing a route

1. **Target named in the request** (ARM ID, `subscription_id`, vault):
   nothing to do — `enforce_target_access` checks it.
2. **Row loaded by database ID**: after loading, call
   `assert_resource_access(row.<arm id or subscription column>, "read" | "write")`.
   For lists, add `arm_scope_clause(...)` or `subscription_scope_clause(...)`
   to the query.
3. **Mutation that changes nothing in Azure** (cache refresh, local render,
   own preference): add it to `READ_PERMITTED_MUTATIONS` with a reason.
4. **Destructive operation**: register a capability in `CAPABILITY_SEEDS` and
   guard with `require_capability(...)`.
5. **Cache keys** for scoped data must include the effective scope (see
   `list_clusters`, `list_vaults`). A shared key serves one user's data to
   another.
6. **Syncs that delete stale rows** must only delete within the subscriptions
   they synced when the scope is narrower than the monitored set (see
   `keyvault_sync_service.full_sync`).
7. **WebSocket routes** bypass router dependencies, so check access in the
   handler (see `AKSLiveSyncHub._may_watch`).
8. **New column on an existing table**: add a `.sql` file under
   `backend/migrations/` (idempotent `IF NOT EXISTS`); `create_all` will not
   add columns.

## Cost cleanup authorization

`POST /api/v1/optimize/cleanup/*` requires the `cost_resource_cleanup`
capability (Write by default, revocable), **write** access to the target
subscription, and Azure RBAC delete rights for the portal's identity.

## Testing

- The `conftest.py` autouse fixture gives every user **unrestricted**
  subscription access, so existing tests stay about roles and behaviour.
  Mark a test `@pytest.mark.real_access` to resolve grants from the test
  database.
- `tests/access_helpers.py` builds the Commissions/BDS fixture world and
  provides `client_as`, `grant` and `make_project_admin`.
- `tests/test_access_scope.py` — classification and resolution rules
- `tests/test_target_access.py` — request target checks, picker behaviour
- `tests/test_row_access.py` — rows by ID, Key Vault inventory, WebSocket
- `tests/test_access_api.py` — grants, requests/approvals, bootstrap, dashboard
- `tests/test_role_matrix.py` — portal-wide role policy (structural)
- `tests/test_subscription_scope.py` — scope resolver
