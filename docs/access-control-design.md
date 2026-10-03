# OpsPortal Access Control Design
**Classification:** Internal — Security Architecture
**Audience:** Security Team, Azure AD Admins, DevOps
**Last updated:** October 2026 (project / Prod-Non-Prod access, Super Admin)

Companion document: [PROJECT_ACCESS.md](PROJECT_ACCESS.md). It has the
project model in detail, the go-live runbook, and the steps for onboarding a
project or an app.

---

## 1. Overview

Access is decided in two independent dimensions. Both must allow a request.

| Dimension | Question | Decided by |
|---|---|---|
| **What** | May this user view or change this kind of thing? | Entra app role (Read / Write / Admin / Super Admin), plus module, page and operation permissions in the portal database |
| **Where** | May this user touch *this* subscription? | Project / app / subscription grants in the portal database |

Every check below runs **on the server**. The frontend hides what the server
would refuse, but that is only for the user's convenience.

```
[Entra ID]               App role in the token: SuperAdmin / Admin / Write / Read
     │
[Token validation]       RS256 signature, audience, issuer, expiry           → 401
     │
[Portal gate]            No recognised app role                              → 403
     │
[Module gate]            No view/edit permission on the API's module         → 403
     │
[Subscription scope]     Lists narrowed to the user's readable subscriptions;
     │                   no subscription at all                              → 403 "Request access"
     │
[Target check]           A subscription named in the request (cluster ID,
     │                   Key Vault, subscription_id) that the user may not
     │                   read (GET) or change (other methods)                → 403
     │
[Role / capability]      require_role / require_capability on the route     → 403
     │
[Row checks]             Stored rows addressed by ID (schedules, alert
     │                   configs) checked against the row's subscription     → 403
     ▼
  Handler runs
```

---

## 2. Entra ID App Roles

| Entra app role | Portal role | Aliases also accepted | Granted where |
|---|---|---|---|
| `OpsPortal.SuperAdmin` | `SUPER_ADMIN` | `superadmin`, `super_admin` | **Entra only.** Nothing in the portal can grant it. |
| `OpsPortal.Admin` | `ADMIN` | `admin` | Entra. It has effect only after a Super Admin assigns the person to a project. |
| `OpsPortal.Write` | `WRITE` | `write`, `contributor` | Entra |
| `OpsPortal.Read` | `READ` | `read`, `reader` | Entra |

The role values are configurable (`ROLE_SUPER_ADMIN`, `ROLE_ADMIN`,
`ROLE_WRITE`, `ROLE_READ`); the defaults above match the app registration.

**Roles are a ladder.** `SUPER_ADMIN ⊃ ADMIN ⊃ WRITE ⊃ READ`, so a route that
requires `WRITE` admits Admins and Super Admins. A route that requires
`SUPER_ADMIN` does **not** admit a plain Admin.

**The role is a ceiling on grants.** A user in the Read group who is granted
Write on a project can still only read there.

### Assigning roles

1. **App registrations → OpsPortal → App roles**: the four roles above.
2. **Enterprise applications → OpsPortal → Users and groups**: assign
   **security groups**, not individuals.
   - Each project should have its own Read / Write / Admin groups, so the
     project owns who joins them.
   - The Super Admin role should go to a small dedicated group, ideally
     PIM-eligible.
3. **Properties → Assignment required = Yes.** Remove any "Default Access"
   (role-less) assignments as well. Those users get a token with no `roles`
   claim and are refused by the portal anyway (see the Entra audit script
   `backend/scripts/audit_portal_entra_access.py`).

Being in an AD group gets a user **into** the portal. Which subscriptions they
see depends on the grants in §5.

---

## 3. Token Validation and Dev Mode

Every `/api/v1` request carries a Bearer **ID token** (`aud` = the app's client
ID). The backend:

1. fetches the Entra JWKS (cached 1 h; refreshed when a signing key is unknown);
2. verifies the RS256 signature, `aud`, `iss` and `exp`;
3. maps the `roles` claim to portal roles;
4. answers **403** to a valid identity with **no recognised role**. There is no
   default role.

**Dev bypass.** It applies only when `ENVIRONMENT=development` **and**
`DEV_AUTH_BYPASS=true`, and only to requests with **no** token. Those requests
run as a synthetic **Super Admin**. An invalid or expired token is always 401.
The backend refuses to start if the bypass is enabled outside development.

> Because the dev user is a Super Admin, restricted behaviour (Read-only,
> Non-Prod-only) cannot be seen in local DEV MODE. Use a real account with
> grants, or the backend tests.

`GET /api/v1/auth/session` (outside the gated router) tells the UI whether the
caller is authenticated, authorized, a Super Admin, and whether they have any
subscription access. Each authorized sign-in is recorded in `portal_users`,
which is the list admins pick from when granting access.

---

## 4. What a Role May Do

Portal-wide policy, enforced by `backend/tests/test_role_matrix.py`. That test
walks every route's dependency tree and fails CI on drift.

| | Read | Write | Admin (Project Admin) | Super Admin |
|---|:---:|:---:|:---:|:---:|
| View every module, including details, exports and log downloads | ✅ | ✅ | ✅ | ✅ |
| Every change on operational pages, including deletes | ❌ | ✅ | ✅ | ✅ |
| Manage grants and decide requests **for their projects** | ❌ | ❌ | ✅ | ✅ (all projects) |
| Create projects and apps, place subscriptions, appoint Project Admins | ❌ | ❌ | ❌ | ✅ |
| Admin console (`/admin`): subscriptions, config, cache, health | ❌ | ❌ | ❌ | ✅ |
| Module / page / capability permissions (`/admin/permissions`) | ❌ | ❌ | ❌ | ✅ |
| Portal-wide maintenance (cache invalidation, compliance snapshot sync, certificate collections, notification history) | ❌ | ❌ | ❌ | ✅ |

All of these apply **only within the subscriptions the user has been granted**
(§5). The exception is Super Admin, which covers every subscription.

A few POST/PUT routes change nothing in Azure and are open to Read users:
cache refresh syncs, chart lint/template, cost queries, log archive download,
the caller's own picker preference, and submitting or cancelling an access
request. They are listed with reasons in `backend/app/core/route_policy.py`
(`READ_PERMITTED_MUTATIONS`), and the role-matrix test keeps that list exact.

---

## 5. Where a User May Work — Project Access

```
Project (Commissions, BDS)  →  App (ATTCC 31599, DWS 17805, …)  →  Subscription (Prod | Non-Prod)
```

- **Grants** give a user **Read** or **Write** on:
  - a project + tier (e.g. "Commissions · Non-Prod"),
  - an app + tier, or
  - one subscription.

  Project and app grants also cover subscriptions added there later.
- **No grant, no subscriptions.** Every module API answers 403 with "Request
  access from the Access page".
- **Project Admin** = the Entra Admin role plus an assignment by a Super Admin.
  It gives read and write on every subscription of that project.
- **Tier.** An unset tier counts as Prod, and DR is Prod. A subscription not
  placed in an app is visible to Super Admins only.
- **Access requests** are approved or rejected line by line by the project's
  admins or a Super Admin. Nobody decides their own request. Grants last until
  revoked.
- **Timing.** Grants are read on every request, so approvals and revocations
  take effect on the next call. Placement changes (project, app, tier) reach
  every replica within 30 seconds.

Details, the go-live transition grant and the onboarding steps are in
[PROJECT_ACCESS.md](PROJECT_ACCESS.md).

---

## 6. Module, Page and Operation Permissions (Database)

Fine-grained "what" control, managed by Super Admins at **Admin → Module &
Page Permissions**.

```
Resource
  ├── resource_type: "module" | "page" | "operation"   (operation = capability, e.g. aks_pod_delete)
  ├── resource_name, route_path, parent_id → module
  └── is_system: seeded at startup, cannot be deleted

Permission
  ├── subject_type: "user" | "role" | "group" (portal team)
  ├── subject_id:   user ID | read/write/admin | team name
  ├── resource_id → Resource
  └── permission_type: "view" | "edit"     (edit implies view)
```

- **Module gate.** Each API prefix belongs to a module (`/api/v1/aks` →
  `aks_operations`, and so on; see `_API_MODULE_PREFIXES` in
  `backend/app/core/authz.py`). The caller needs view or edit on it. This is
  enforced on the API, not just the UI.
- **Inheritance.** A grant on a module covers its pages.
- **Capabilities.** Destructive operations are `operation` resources checked
  with `require_capability(...)`. Write users get them by default and an admin
  can revoke them. A capability missing from the database falls back to its
  role requirement, never to open access.
- **Admins** (Admin and Super Admin) skip module and capability checks. They do
  **not** skip the subscription checks in §5. Only a Super Admin is
  unrestricted there.
- **Defaults** are seeded on every start from
  `backend/app/core/resource_registry.py`: Read gets view and Write gets edit
  on every non-admin module.
- **Legacy `environment_scope`.** The old per-permission all/prod/nonprod
  field was never enforced. It is no longer offered in the UI, and Prod /
  Non-Prod is now decided by project grants (§5).

---

## 7. Where It Is Enforced

| Layer | Code |
|---|---|
| Token validation, role mapping, `require_role` | `backend/app/auth/__init__.py` |
| Portal gate, module gate, capabilities | `backend/app/core/authz.py` (router dependencies, not middleware) |
| Subscription scope and the "no access" 403 | `backend/app/core/subscription_scope.py` (`bind_subscription_scope`) |
| Grant resolution, row-level helpers | `backend/app/core/access_scope.py` |
| Subscriptions named in a request | `backend/app/core/target_access.py` (`enforce_target_access`) |
| Read-only mutations list | `backend/app/core/route_policy.py` |
| Access API (grants, requests, approvals) | `backend/app/api/v1/endpoints/access.py`, `backend/app/services/access_service.py` |
| K8s Dashboard | `aks_dashboard.py`. The launch checks the cluster's subscription, and a session is writable only with write access there. |
| AKS live-watch WebSocket | `aks_live_sync_hub.py`. Subscribing to a cluster checks its subscription. |
| Router order | `backend/app/api/v1/router.py`: portal gate → module gate → scope → target check |

Plugin routers get the same dependencies (`backend/app/plugins/__init__.py`).

**Startup guard.** If the database lacks the project-access columns (for
example, the migration could not run), the backend refuses to start and logs
`access_schema_incomplete`. Without the columns every request would fail.

---

## 8. Frontend Guards

All of these are UX only; the server enforces everything above.

| Guard | Where | Rule |
|---|---|---|
| `ProtectedRoute module/page` | module pages | Page permission, then: no subscription access (and not Super Admin) → "Request access" panel |
| `SuperAdminRoute` | `/admin`, `/admin/permissions` | Super Admin only; explains why otherwise |
| `AccessAdminRoute` | `/access/manage` | Super Admin, or Admin assigned to at least one project |
| Nav | `App.tsx` | "My Access" for everyone; "Manage Access" for Super Admins and Project Admins; "Admin" for Super Admins |

Role and access facts come from `/api/v1/auth/session`, not from the ID token.

---

## 9. Audit

Changes are written to `audit_logs` after they commit:

- permission changes and all access changes: grants, revocations, requests,
  decisions, projects, apps, placements and project admins
  (`resource_type = 'access_management'`);
- AKS operations, **including denials**;
- Key Vault, certificate and cost-cleanup operations.

Super Admins can read the permission audit log at
`GET /api/v1/permissions/audit-log`. Denials by the subscription checks are
also logged (`subscription_access_denied`, `row_access_denied`).

---

## 10. Revocation Timing

| Change | Takes effect |
|---|---|
| Grant revoked / approved, project admin removed | Next request |
| Subscription moved between apps, tier changed, project deactivated | Within 30 s on every replica |
| Entra role or AD group membership changed | When the user next gets a token (up to ~1 h). For immediate effect, use **Entra → Revoke sessions**. |

---

## 11. Access Decision Flow (Example)

A Write user with *Commissions · Non-Prod · Write* scales a deployment on a
Prod ATTCC cluster:

```
Token valid, role WRITE ............................................. pass
Module gate: aks_operations view/edit (seeded for write) ............ pass
Scope: readable = Commissions Non-Prod subscriptions (non-empty) .... pass
Target check: cluster_id → ATTCC Prod subscription, needs write ..... 403
```

The same request against the Non-Prod cluster passes every layer. A user with
no grant is stopped at the scope step with "Request access from the Access
page".

---

## 12. Known Gaps

1. **Not yet project-scoped** (not tied to an Azure subscription). These are
   controlled only by module permissions:
   - certificates (Keyfactor collections),
   - Synapse checksum runs addressed by workspace name,
   - custom expiry alerts, the alert scheduler, notification history,
   - budget run-rate, the checksum metrics snapshot.

   See [PROJECT_ACCESS.md §5](PROJECT_ACCESS.md#not-yet-project-scoped).
2. **Single Azure identity.** The portal reaches every project's subscriptions
   with one identity. A separate identity per project would limit what a
   compromise can reach.
3. **Groups claim unused.** Roles come only from app roles in the `roles`
   claim; `groups` is parsed but ignored. Assign security groups **to app
   roles** (§2).
4. **Token lifetime.** Removing someone from an AD group takes effect at their
   next token. Portal grants take effect immediately.
