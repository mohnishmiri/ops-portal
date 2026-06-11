# OpsPortal Access Control Design
**Classification:** Internal — Security Architecture  
**Audience:** Security Team, Azure AD Admins, DevOps

---

## 1. Overview

OpsPortal uses a **four-layer access control model**:

```
[Azure AD / Entra ID]
       │  App Role assignment (Admin / Write / Read)
       ▼
[JWT Token Validation]
       │  Signature (RS256), audience, issuer, expiry
       ▼
[Role → UserContext Mapping]
       │  OpsPortal.Admin → ADMIN | OpsPortal.Write → WRITE | OpsPortal.Read → READ
       ▼
[Permission Records (DB)]
       │  (role, module/page, view|edit) — admin configurable
       ▼
[Frontend Route Guards]
       │  ProtectedRoute + PermissionsContext + Nav visibility
       ▼
[User sees page or AccessDenied]
```

---

## 2. Layer 1 — Azure AD / Entra ID App Roles

### How Roles Are Assigned

OpsPortal uses **Azure AD App Roles** (not Security Groups) defined in the App Registration manifest. The three roles are:

| Entra App Role        | Portal Role | Aliases also accepted              |
|-----------------------|-------------|------------------------------------|
| `OpsPortal.Admin`     | `ADMIN`     | `admin`                            |
| `OpsPortal.Write`     | `WRITE`     | `write`, `contributor`             |
| `OpsPortal.Read`      | `READ`      | `read`, `reader`                   |

**How roles flow:** When a user authenticates, Entra ID issues a JWT token. The `roles` claim in the token contains the App Roles assigned to that user. Example:

```json
{
  "sub": "abc-123",
  "name": "Jane Smith",
  "email": "jane@company.com",
  "roles": ["OpsPortal.Write"],
  "aud": "<client-id>",
  "iss": "https://login.microsoftonline.com/<tenant>/v2.0"
}
```

### Assigning App Roles via Entra ID

In the Azure Portal → **App registrations → OpsPortal → App roles**:
1. Create roles: `OpsPortal.Admin`, `OpsPortal.Write`, `OpsPortal.Read`
2. Go to **Enterprise Applications → OpsPortal → Users and groups**
3. Assign individual users **or** Security Groups to each App Role

> **Best practice:** Assign a Security Group (e.g., `SG-OpsPortal-Admins`) to the App Role. This way, adding/removing someone from the AD group immediately controls their portal role — no individual user assignments needed.

---

## 3. Layer 2 — JWT Token Validation

Every API request to the backend must carry a Bearer token. The backend:

1. Fetches the Entra ID JWKS (cached 1 hour, auto-refreshed on key rotation)
2. Verifies RS256 signature
3. Validates `aud` = `AZURE_CLIENT_ID`, `iss` = expected tenant issuer, `exp`
4. Extracts `roles`, `sub`, `oid`, `name`, `email`
5. Maps roles → `UserContext` with `roles: [UserRole.ADMIN | WRITE | READ]`
6. Rejects users with **no recognised App Role** (HTTP 403)

If a user has no App Role assigned in Entra ID, they cannot log in at all.

---

## 4. Layer 3 — Permission Records (Database RBAC)

This layer is the fine-grained control managed through **Admin → Access Management**.

### Data Model

```
Resource (module/page)
  ├── resource_type: "module" | "page"
  ├── resource_name: "cost_management", "amortized_costs", etc.
  ├── is_system: true (cannot be deleted)
  └── parent_id → parent module

Permission
  ├── subject_type: "role" | "user"
  ├── subject_id: "read" | "write" | <azure-oid>
  ├── resource_id → Resource
  └── permission_type: "view" | "edit"
```

### How the Admin Can Control Access

In **Admin → Access Management → Permissions tab**, an admin can:

| Action | Effect |
|--------|--------|
| Grant `read` role `view` on `amortized_costs` | All users with Read role see Amortized Costs page |
| Grant `write` role `edit` on `aks_main` | Write users can perform actions in AKS page |
| Grant user `<oid>` `view` on `keyvault_main` | That specific user sees Key Vault even if their role doesn't |
| Revoke `read` role `view` on `compliance_main` | Read users can no longer see the Compliance page |

### Permission Inheritance

**Module → Page inheritance:** If a role has permission on a module, it inherits permission on all child pages. Example: granting `write` role `view` on `cost_management` automatically grants `view` on `leadership_dashboard` and `amortized_costs`.

### Admin Role Override

`ADMIN` role **always bypasses** permission record checks. Admins see everything regardless of what's in the DB. This cannot be restricted via the permissions UI — it is enforced in code.

---

## 5. Layer 4 — Frontend Route Guards

Every page route is wrapped in `<ProtectedRoute module="…" page="…">`.

**Check sequence:**
1. `isAdmin` → pass through (no DB check)
2. Permissions loading → show spinner (prevents false-deny on first render)
3. `canViewModule(module)` → checks permission record for the module
4. `canViewPage(page)` → checks permission record for the page
5. Fail → render `<AccessDenied>` component

**Nav bar:** Menu items are hidden if the user has no view permission for that module/page. Users never see links they cannot access.

---

## 6. Default Permission Matrix (Seeded on Startup)

The following grants are seeded automatically when the backend starts. Admins can modify these at any time through the UI.

| Resource | Type | read role | write role | admin role |
|----------|------|-----------|------------|------------|
| Cost Management | Module | view | view + edit | full (role-gated) |
| Leadership Dashboard | Page | view | view + edit | full |
| Amortized Costs | Page | view | view + edit | full |
| AKS Operations | Module | view | view + edit | full |
| AKS Main | Page | view | view + edit | full |
| Compliance | Module | view | view + edit | full |
| Compliance Dashboard | Page | view | view + edit | full |
| Key Vault | Module | view | view + edit | full |
| Key Vault Dashboard | Page | view | view + edit | full |
| Infra Alerts | Module | view | view + edit | full |
| Infra Alerts Dashboard | Page | view | view + edit | full |
| **Admin Panel** | Module | — | — | role-gated (admin only) |
| **Admin Dashboard** | Page | — | — | role-gated (admin only) |
| **Access Management** | Page | — | — | role-gated (admin only) |

> Admin pages are protected at the **role level** (code-enforced), not via permission records. No permission grant can give a non-admin user access to admin pages.

---

## 7. Recommended Entra ID Setup

```
Azure AD App Registration: OpsPortal
├── App Role: OpsPortal.Admin
│   └── Assigned to: Security Group "SG-OpsPortal-Admins"
│       └── Members: [DevOps leads, Security team]
├── App Role: OpsPortal.Write
│   └── Assigned to: Security Group "SG-OpsPortal-Contributors"
│       └── Members: [Engineers, analysts who need to take actions]
└── App Role: OpsPortal.Read
    └── Assigned to: Security Group "SG-OpsPortal-Readers"
        └── Members: [Leadership, stakeholders, auditors]
```

**Adding a user to the portal:** Add them to the appropriate AD security group. The role flows automatically into their next login token — no portal config change needed.

**Removing access:** Remove from the AD group. Their existing JWT will still work until it expires (typically 1 hour). For immediate revocation, use **Entra ID → Revoke all refresh tokens** for that user.

---

## 8. Access Control Gaps & Recommendations

### Gap 1 — Azure AD Groups Not Used in Role Mapping ⚠️

**Current state:** The `groups` claim is parsed in the JWT model but is **not used** in role mapping. Only the `roles` claim (App Roles) is used.

**Risk:** If your org assigns AD Security Groups directly to the app (instead of App Roles), those group memberships are silently ignored — users get no access.

**Fix:** Either:
- (Recommended) Use App Roles with Security Groups assigned to them (as shown above)
- Or extend `_map_roles()` in `app/auth/__init__.py` to also check `claims.groups` against a configured group-ID → role mapping

### Gap 2 — API Endpoints Don't Enforce Page-Level Permissions ⚠️

**Current state:** API endpoints use `require_role(UserRole.READ)` or `require_role(UserRole.WRITE)` — they check the **role tier** but not the **page-level permission record**. A `write` role user whose `amortized_costs` page permission has been revoked can still call the `/api/v1/costs/amortized/summary` endpoint directly via curl or API client.

**Risk:** Fine-grained page permission revocation only blocks the UI, not the API.

**Recommended fix:** For sensitive endpoints, add a permission record check to the FastAPI dependency:
```python
# Example: require the user to have 'view' on amortized_costs resource
async def require_page_permission(resource_name: str, perm: str = "view"):
    async def _checker(user=Depends(get_current_user), db=Depends(get_db)):
        if user.is_admin:
            return user
        # check DB permission record for user or their roles
        ...
    return _checker
```

### Gap 3 — No Token Revocation on Permission Change ⚠️

**Current state:** When a permission is revoked in the Access Management UI, the user's frontend updates within 5 minutes (React Query `staleTime`). But their JWT is still valid for up to 1 hour.

**Risk:** A user whose permission was revoked can still call the API directly using their current token until it expires.

**Recommendation:** For high-sensitivity revocations (removing admin access, revoking all access), use **Entra ID → Revoke sign-in sessions** for that user, then use Entra Continuous Access Evaluation (CAE) to propagate revocation in near-real-time.

### Gap 4 — Subscription-Level Access Control ✅ (partially implemented, v1.2.0)

**Implemented (v1.2.0):**

1. **Admin monitored ceiling** — Sync jobs and the maximum data set are defined by `admin_subscriptions` rows where `enabled = True AND monitored = True` (`get_monitored_subscription_ids()`).
2. **Per-user read scope** — Each user can persist a subset via **Subscription scope** (nav picker). Stored in `user_subscription_preferences`; applied per request through `bind_subscription_scope` on `/api/v1` and `get_scoped_subscription_ids()` in read-path services.
3. **Effective formula:** `monitored ∩ allowed_subscriptions ∩ selected_subscription_ids` (empty selection = all monitored).

**Still a gap:** `UserContext.allowed_subscriptions` is not populated from Entra ID or a DB mapping today (empty = all monitored). To enforce org-wide RBAC per subscription, populate that field during token processing and the existing resolver will intersect it automatically.

**Leadership scope (v1.2.0+):** Narrowed subscription picker filters leadership KPIs via scoped amortized DB aggregation and per-scope page-cache keys. Global `leadership_dashboard_snapshots` (`environment=ALL`) remain the source for full-monitored views; partial scopes do not read the global snapshot.

### Gap 5 — No Audit Log for Permission Changes ℹ️

**Current state:** Permission grants and revocations are logged to the structlog at INFO level but there is no dedicated audit trail queryable through the portal.

**Recommendation:** Add an `audit_log` table and write an entry on every permission create/delete with: `who changed`, `what changed`, `old value`, `new value`, `timestamp`.

---

## 9. Access Decision Flow (End-to-End)

```
User navigates to /env-costs (Amortized Costs)
│
├─ [Entra ID] User authenticated? JWT valid?
│   └─ No → Redirect to login
│
├─ [Backend] JWT validated (RS256 + audience + issuer + expiry)?
│   └─ No → 401 Unauthorized
│
├─ [Backend] User has recognised App Role?
│   └─ No → 403 "No app role assigned"
│
├─ [Frontend] isAdmin?
│   └─ Yes → Access granted, skip all further checks
│
├─ [Frontend] Permission loaded: canViewModule("cost_management")?
│   └─ No → AccessDenied component rendered
│
├─ [Frontend] canViewPage("amortized_costs")?
│   └─ No → AccessDenied component rendered
│
└─ [User sees Amortized Costs Dashboard]
```

---

## 10. Quick Reference: Who Can Do What

| Action | read | write | admin |
|--------|------|-------|-------|
| View all dashboards & pages | ✅ | ✅ | ✅ |
| Trigger manual Azure sync | ❌ | ✅ | ✅ |
| Add/modify subscriptions | ❌ | ✅ | ✅ |
| Access Admin Dashboard | ❌ | ❌ | ✅ |
| Manage permissions (RBAC) | ❌ | ❌ | ✅ |
| Add/remove permission grants | ❌ | ❌ | ✅ |
| Grant per-user access overrides | ❌ | ❌ | ✅ |
| See other users' permissions | ❌ | ❌ | ✅ |
| Revoke all permissions for a page | ❌ | ❌ | ✅ |
| Narrow subscription scope (personal) | ✅ | ✅ | ✅ |
| Delete unattached disks / disconnected PEs | ❌ | ❌ | ✅ |
