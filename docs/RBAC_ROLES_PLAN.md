# OpsPortal RBAC — Role-Based Access Control Plan

> Role definitions, team assignments, and endpoint protection strategy.

---

## 1. Role Definitions

| Role | Config Key | Entra App Role Value | Purpose |
|------|-----------|---------------------|---------|
| **Admin** | `ROLE_ADMIN` | `OpsPortal.Admin` | Full access — manage subscriptions, trigger syncs, view all dashboards, admin panel |
| **Write** | `ROLE_WRITE` | `OpsPortal.Write` | Operational access — trigger syncs, export data, view all dashboards |
| **Read** | `ROLE_READ` | `OpsPortal.Read` | View-only — browse dashboards and reports, no mutations |

### Role Hierarchy

```
Admin ──▶ Write ──▶ Read
  │         │         │
  │         │         └── View dashboards, reports, cost data
  │         └──────────── Trigger syncs, export, modify non-admin resources
  └────────────────────── Manage subscriptions, user config, admin panel
```

- **Admin** implicitly satisfies all role requirements (enforced in `require_role()`)
- **Write** includes all Read capabilities
- **Read** is the default fallback when no recognized role is present

---

## 2. Team-to-Role Assignment Matrix

| Team / Group | Role | Access Level | Justification |
|---|---|---|---|
| **Infra / Ops** | `OpsPortal.Admin` | Full admin | Manage subscriptions, configure sync schedules, access admin panel |
| **DevOps / SRE Leads** | `OpsPortal.Write` | Write | Trigger data syncs, export reports, manage operational tasks |
| **Senior Developers** | `OpsPortal.Write` | Write | Trigger syncs during debugging, export cost data for analysis |
| **Developers** | `OpsPortal.Read` | Read-only | View cost breakdowns, optimization recommendations |
| **QA / Test Team** | `OpsPortal.Read` | Read-only | Validate dashboard data, verify test environment costs |
| **Management / Leadership** | `OpsPortal.Read` | Read-only | View leadership dashboard, cost summaries |
| **Finance / FinOps** | `OpsPortal.Read` | Read-only | View cost analytics for budgeting and chargebacks |

### Recommended Azure AD Security Groups

```
SG-OpsPortal-Admins   →  OpsPortal.Admin   (Infra/Ops team members)
SG-OpsPortal-Writers   →  OpsPortal.Write   (DevOps leads, senior devs)
SG-OpsPortal-Readers   →  OpsPortal.Read    (Developers, QA, leadership)
```

---

## 3. Endpoint Protection Map

### Read-Only Endpoints (all authenticated users)

These require only `get_current_user` — any role can access.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/leadership/summary` | GET | Leadership cost summary |
| `/api/v1/leadership/trends` | GET | Cost trend data |
| `/api/v1/costs/amortized-summary` | GET | Amortized cost analytics |
| `/api/v1/costs/amortized-drilldown` | GET | Resource-level cost drilldown |
| `/api/v1/costs/amortized/sync-status` | GET | Sync status indicator |
| `/api/v1/costs/env-daily/summary` | GET | Daily cost by environment |
| `/api/v1/costs/env-daily/trend` | GET | Daily cost trends |
| `/api/v1/costs/env-daily/sync-status` | GET | Daily sync status |
| `/api/v1/optimization/recommendations` | GET | Optimization items |
| `/api/v1/optimization/summary` | GET | Optimization summary |
| `/api/v1/keyvault/status` | GET | Key Vault health |
| `/api/v1/keyvault/secrets` | GET | KV secret expiry |
| `/api/v1/keyvault/sync-status` | GET | KV sync status |
| `/api/v1/aks/operations` | GET | AKS cluster status |
| `/api/v1/compliance/summary` | GET | Compliance posture |
| `/api/v1/compliance/resources` | GET | Resource compliance |
| `/api/v1/infra-alerts/active` | GET | Active alerts |
| `/api/v1/infra-alerts/summary` | GET | Alert summary |

### Write Endpoints (Write + Admin)

These require `require_role(UserRole.WRITE)` — Admin also passes.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/costs/amortized/sync` | POST | Trigger amortized cost sync from Azure Cost Management APIs |
| `/api/v1/costs/env-daily/sync` | POST | Trigger daily cost sync from Azure Cost Management API |
| `/api/v1/keyvault/sync` | POST | Trigger Key Vault sync |

### Admin-Only Endpoints

These require `require_role(UserRole.ADMIN)`.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/admin/subscriptions` | GET | List managed subscriptions |
| `/api/v1/admin/subscriptions` | POST | Add new subscription |
| `/api/v1/admin/subscriptions/{id}` | PUT | Update subscription |
| `/api/v1/admin/subscriptions/{id}` | DELETE | Delete subscription |
| `/api/v1/admin/subscriptions/{id}/toggle` | POST | Enable/disable subscription |
| `/api/v1/admin/subscriptions/sync` | POST | Sync from Azure |
| `/api/v1/admin/dashboard` | GET | Admin dashboard stats |

---

## 4. Implementation Code Changes

### 4.1 Backend — Apply `require_role` to Write Endpoints

```python
# In costs.py — sync endpoints
from app.auth import require_role
from app.models.auth import UserRole, UserContext

@router.post("/amortized/sync")
async def sync_amortized_costs(
    months: int = Query(2, ge=1, le=12),
    user: UserContext = Depends(require_role(UserRole.WRITE)),  # ← Add this
    db: AsyncSession = Depends(get_db),
):
    svc = AmortizedCostSyncService(db)
    result = await svc.full_sync(months=months, triggered_by=user.display_name)
    return result
```

### 4.2 Backend — Apply `require_role` to Admin Endpoints

```python
# In admin.py — all mutation endpoints
@router.post("/subscriptions")
async def create_subscription(
    payload: SubscriptionCreate,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),  # ← Add this
    db: AsyncSession = Depends(get_db),
):
    ...
```

### 4.3 Frontend — Conditionally Hide UI Elements by Role

Future enhancement: Create a `useCurrentUser` hook that exposes roles from the MSAL token, then hide/show based on role:

```typescript
// Potential hook: useUserRole.ts
import { useMsal } from "@azure/msal-react";
import { isDevMode } from "../config/authConfig";

export type AppRole = "admin" | "write" | "read";

export function useUserRoles(): AppRole[] {
  if (isDevMode) return ["admin"]; // Dev mode = full access

  const { accounts } = useMsal();
  const account = accounts[0];
  if (!account) return ["read"];

  // Azure AD puts app roles in idTokenClaims.roles
  const roles = (account.idTokenClaims as any)?.roles as string[] || [];

  const mapped: AppRole[] = [];
  for (const r of roles) {
    const lower = r.toLowerCase();
    if (lower.includes("admin")) mapped.push("admin");
    else if (lower.includes("write") || lower.includes("contributor")) mapped.push("write");
    else mapped.push("read");
  }

  return mapped.length ? mapped : ["read"];
}

export function useIsAdmin(): boolean {
  return useUserRoles().includes("admin");
}

export function useCanWrite(): boolean {
  const roles = useUserRoles();
  return roles.includes("admin") || roles.includes("write");
}
```

Then in components:

```tsx
// Hide sync button for read-only users
const canWrite = useCanWrite();

{canWrite && (
  <button onClick={handleSync}>Sync from Azure</button>
)}

// Hide admin nav item for non-admins
const isAdmin = useIsAdmin();

{isAdmin && (
  <NavLink to="/admin">Admin</NavLink>
)}
```

---

## 5. Security Considerations

1. **Backend is the enforcement layer** — Frontend role checks are for UX convenience only. The backend `require_role()` dependency returns 403 if the user's JWT doesn't have the required role.

2. **Default to READ** — If a user's token has no recognized roles, `_map_roles()` assigns `UserRole.READ` as fallback. This prevents lockout but ensures no accidental write access.

3. **Admin bypass** — `require_role()` checks `user.is_admin` first, so admins always pass any role check. This is intentional to avoid admin lockout scenarios.

4. **Audit trail** — The `UserContext` is attached to `request.state` by `get_current_user()`. Future middleware can log all API calls with the user identity for audit purposes (the `AuditLogEntry` model is already defined).

5. **Subscription-level access** — The `UserContext.allowed_subscriptions` field supports future per-subscription RBAC. Currently empty (= access all). Can be populated from a database mapping table.

---

## 6. Implementation Timeline

| Phase | Effort | Description |
|---|---|---|
| Azure AD role setup | 30 min | Create 3 App Roles in App Registration (Step 3 in Entra doc) |
| Group assignment | 30 min | Create AD groups, assign roles, add members |
| Backend `require_role` | 1-2 hours | Add dependency to ~10 write/admin endpoints |
| Frontend role hooks | 1-2 hours | Create `useUserRoles` hook, conditionally hide UI elements |
| Testing | 1-2 hours | Test with users of each role level |
| **Total** | **4-7 hours** | Mostly configuration + testing |

---

*Document generated for OpsPortal — `apm0014313-attcc-ops-portal/azure-ops-portal`*
