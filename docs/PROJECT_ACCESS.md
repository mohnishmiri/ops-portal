# Project Access — Prod / Non-Prod, Projects, Super Admin

How the Ops Portal decides **where** a user may work, how to go live with it,
and how to onboard a new project or app.

Roles from Entra still decide **what** a user may do (Read views, Write changes).
This layer adds **where**: which subscriptions a user may see and change.

---

## 1. The model

```
Super Admin                     (Entra app role OpsPortal.SuperAdmin — everything)
├── Commissions   (Project)     ← Project Admin(s)
│   ├── ATTCC  (31599)  → Prod subscription(s), Non-Prod subscription(s)
│   ├── DWS    (17805)  → Prod, Non-Prod
│   └── HZNREP (18296)  → Prod, Non-Prod
└── BDS           (Project)     ← Project Admin(s)
    └── its apps        → Prod, Non-Prod
```

| Who | How they get it | What they can reach |
|---|---|---|
| **Super Admin** | Entra app role `OpsPortal.SuperAdmin`. Cannot be granted inside the portal. | Every project and subscription, read and write. The Admin console (`/admin`, `/admin/permissions`). |
| **Project Admin** | Entra `OpsPortal.Admin` role **and** appointed to a project by a Super Admin | Every subscription in their project(s), read and write. Grants and approvals for their project(s) only. |
| **Write / Read users** | Entra `OpsPortal.Write` / `OpsPortal.Read` group, **plus** grants | Only what they have been granted |

**Grants.** A grant gives a user **Read** or **Write** on:

- a **project + tier** (e.g. "Commissions · Non-Prod"), or
- an **app + tier** (e.g. "DWS · Prod"), or
- a single **subscription** (for exceptions).

Project and app grants also cover subscriptions added there later.

**Rules**

- No grant means no subscriptions. Every module API answers 403 with
  "Request access from the Access page".
- The Entra role is a ceiling. A user in the Read group who is granted Write
  can still only read.
- Grants do not expire. They last until an admin revokes them.
- **Prod / Non-Prod** comes from each subscription's tier. PreProd, UAT, Perf
  and Dev are Non-Prod. **DR is Prod.** A subscription with no tier counts as
  Prod.
- A subscription not yet placed in an app is visible to Super Admins only.

**Access requests.**

1. Any signed-in user can request a project or app, Prod and/or Non-Prod, at
   Read or Write (up to their Entra role), with a justification.
2. The admins of that project and all Super Admins are emailed.
3. Each line is approved or rejected separately. The approver may lower the
   level but not raise it. Nobody can decide their own request.
4. The requester is emailed the outcome. Approval takes effect on their next
   page load; no re-login is needed. Revocation also takes effect at once.

Every grant, revocation, request, decision and placement change is written to
`audit_logs` with `resource_type = 'access_management'`.

---

## 2. Go-live runbook

### Before deploying

1. **Create the Super Admin app role in Entra.** In the Ops Portal app
   registration, under *App roles*, add:
   - Display name `Ops Portal Super Admin`
   - Value `OpsPortal.SuperAdmin` (or set `ROLE_SUPER_ADMIN` to the value you use)
   - Allowed member types: Users/Groups
2. **Assign it** to the platform owner(s) on the Enterprise App. Prefer a
   dedicated group, with PIM if available.

   > Without this step, nobody reaches the Admin console after deployment.
   > `/admin` and `/admin/permissions` now require Super Admin.
3. **Check `PORTAL_BASE_URL`** (links in access-request emails). The chart
   defaults it to `https://<ingress host>`, which CI sets from
   `DEV_HOSTNAME` / `PROD_HOSTNAME`; stage sets it explicitly in
   `values-dev.yaml`. Override `backend.env.PORTAL_BASE_URL` only if the public
   URL differs from the ingress host.

4. **Make sure the database user owns `admin_subscriptions`.** The migration
   `backend/migrations/add_project_access.sql` adds two columns to it at
   startup. If it cannot, the backend refuses to start and logs
   `access_schema_incomplete`; the reason is in the earlier
   `sql_migration_failed` line. In that case, apply the file as the table owner
   (`psql -f backend/migrations/add_project_access.sql`) and restart.

### On first start (automatic, runs once)

The backend:

1. Creates project **Commissions**.
2. Creates one app per AppID found in subscription names
   (`ACC-PROD-31599-ATTCC` → app 31599 "ATTCC").
3. Places each subscription in its app with its tier. Names with no AppID go
   to an app named **Unclassified**.
4. Adds a **transition grant**: *everyone → Commissions, Prod and Non-Prod,
   Write*, capped by each user's Entra role. Access is exactly what it is
   today, so nobody is locked out.

A marker (`admin_config.access_model_bootstrapped_at`) stops this from ever
running again.

### After deploying

As Super Admin, under **Access Management**:

1. **Subscriptions** tab: check the tiers, and move anything in
   *Unclassified* to the right app.
2. **Projects & Apps**: appoint the Commissions **Project Admins**. Candidates
   need the Entra Admin role and must have signed in once.
3. **User Access**: give the ops team *Commissions · Prod + Non-Prod · Write*,
   and the dev team *Commissions · Non-Prod · Write*. Alternatively, ask people
   to submit requests and approve them.
4. **Remove the transition grant** (the amber banner on the User Access tab).
   From then on, only explicit grants count.

> Remove the transition grant **before onboarding a second project**.
> Otherwise every user from the new project also gets Commissions access.

---

## 3. Onboarding a new project (e.g. BDS)

| Step | Who | Where |
|---|---|---|
| Create the project's Read / Write / Admin AD groups and assign them to the Ops Portal app roles. The project owns who joins its groups. | Entra admin | Entra |
| Grant the portal's Azure identity access to the project's subscriptions: Reader, Cost Management Reader, and the AKS / Key Vault roles for the operations they need. Check network access to private AKS clusters. | Azure admin | Azure |
| Add/discover the subscriptions and enable monitoring | Super Admin | Admin console |
| Create the project, add its apps (by AppID). Matching subscriptions are placed automatically. | Super Admin | Access Management → Projects & Apps |
| Confirm tiers; place any subscriptions whose names carry no AppID | Super Admin | Access Management → Subscriptions |
| Appoint the project's admins | Super Admin | Projects & Apps |
| Grant users, or approve their requests | Project Admin | User Access / Requests |

## 4. Onboarding a new app into an existing project

1. **Add the app** (name + AppID) under its project. Subscriptions named
   `ACC-{PROD|NPRD}-{AppID}-…` are placed with their tier straight away.
   Subscriptions discovered later are placed automatically too.
2. **Grant Azure access** to the portal's identity on those subscriptions.
3. **No grants needed.** Anyone with a grant on the whole project already has
   the new app, at the tier and level they hold.

---

## 5. Where it is enforced (for engineers)

| Layer | File | What it does |
|---|---|---|
| Scope resolution | `backend/app/core/access_scope.py` | Grants + project admins → readable / writable subscriptions per request. The topology is cached 30 s per process; grants are read every request. |
| List filtering | `backend/app/core/subscription_scope.py` | The picker and every `get_scoped_subscription_ids()` caller see only readable subscriptions. Users with none get 403 on module APIs before any service runs. |
| Request targets | `backend/app/core/target_access.py` | Every subscription a request names — ARM IDs (`cluster_id`, `resource_id`), `subscription_id`-like fields, Key Vault URIs/names — must be readable (GET, and the read-only mutations in `route_policy.py`) or writable (every other change). |
| Rows by ID | `assert_resource_access` / `arm_scope_clause` | Environment schedules, sequences and history; infra-alert configs and alerts; Key Vault inventory. |
| K8s Dashboard | `aks_dashboard.py` | An environment is listed and launchable only if the user can read its cluster's subscription. The session is writable only with write access. |
| AKS live watch (WebSocket) | `aks_live_sync_hub.py` | Subscribing to a cluster checks its subscription. WebSocket routes skip the HTTP router's checks. |
| Startup guard | `main.py` / `core/database.py` | Refuses to start when `admin_subscriptions.app_id` / `tier` are missing (`access_schema_incomplete`). |

The full layer-by-layer model is in
[access-control-design.md](access-control-design.md).

**Adding a route.** If it names its target by ARM ID, `subscription_id` or
vault, nothing is needed. If it loads a row by database ID, call
`assert_resource_access(row.<arm or subscription column>, "read" | "write")`
after loading. A new state-changing route that READ users may call must be
listed in `route_policy.READ_PERMITTED_MUTATIONS`; `tests/test_role_matrix.py`
enforces this.

### Not yet project-scoped

These are not tied to an Azure subscription, so they are controlled only by
module permissions:

- Certificates (Keyfactor collections)
- Checksum runs and schedules addressed by Synapse workspace name
- Custom expiry alerts
- The alert scheduler
- Notification history
- Budget run-rate (`budget_config.json`)
- The checksum metrics snapshot

Next steps:

- Map Keyfactor collections (`AP-KF-<APP><id>`) and Synapse workspaces to apps.
- Move per-project settings out of global env vars: K8s Dashboard clusters and
  tokens, Keyfactor credentials, notification recipients, budgets.

The portal also still uses a single Azure identity for every project. A
separate identity per project would limit what a compromise can reach.
