# Entra ID (Azure AD) Authentication — Step-by-Step Implementation Plan

> **OpsPortal** | Authentication & RBAC Activation Guide

---

## 📋 Current State

The OpsPortal codebase **already has full authentication and RBAC infrastructure built**:

| Layer | File | Status |
|-------|------|--------|
| Backend JWT validation | `backend/app/auth/__init__.py` | ✅ Complete — JWKS caching, token decode, role mapping, `get_current_user`, `require_role` |
| Backend auth models | `backend/app/models/auth.py` | ✅ Complete — `UserRole` enum (ADMIN/WRITE/READ), `TokenClaims`, `UserContext` |
| Backend config | `backend/app/core/config.py` | ✅ Complete — `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, role names configured |
| Frontend MSAL | `frontend/src/config/authConfig.ts` | ✅ Complete — MSAL config, MFA claims challenge, dev-mode bypass |
| Frontend API client | `frontend/src/services/apiClient.ts` | ✅ Complete — Bearer token injection, silent renewal, 401 redirect |
| Frontend auth gate | `frontend/src/components/App.tsx` | ✅ Complete — `MsalProvider`, `AuthenticatedTemplate`, login page |
| Dev mode bypass | Both frontend & backend | ✅ Complete — `isDevMode` / `ENVIRONMENT=development` |

**What remains is Azure Portal configuration** — creating the App Registration, defining roles, assigning users, and setting environment variables. This document provides every step.

---

## Step 1: Create the App Registration in Azure Entra ID

### 1.1 Register the Application

1. Go to **Azure Portal** → **Microsoft Entra ID** → **App registrations** → **+ New registration**
2. Fill in:
   - **Name**: `OpsPortal` (or `OpsPortal-<env>` for per-environment registrations)
   - **Supported account types**: *Accounts in this organizational directory only (AT&T single tenant)*
   - **Redirect URI** (Web):
     - For development: `http://localhost:5177` (Vite dev server port)
     - Add additional URIs later for staging/production
3. Click **Register**
4. Note down from the **Overview** page:
   - **Application (client) ID** → this is `AZURE_CLIENT_ID` / `VITE_AZURE_CLIENT_ID`
   - **Directory (tenant) ID** → this is `AZURE_TENANT_ID` / `VITE_AZURE_TENANT_ID`

### 1.2 Configure Authentication

1. Go to **Authentication** blade
2. Under **Platform configurations** → **Web**:
   - Add all **Redirect URIs**:
     ```
     http://localhost:5177                      (local dev)
     http://localhost:5173                      (alternative local)
     https://opsportal.<your-domain>.com        (production)
     https://opsportal-staging.<your-domain>.com (staging)
     ```
   - **Front-channel logout URL**: `https://opsportal.<your-domain>.com`
3. Under **Implicit grant and hybrid flows**:
   - ❌ **Do NOT check** "Access tokens" or "ID tokens" (we use auth code flow with PKCE via MSAL.js — more secure)
4. Under **Supported account types**: Confirm *Single tenant*
5. Click **Save**

### 1.3 Create a Client Secret (for backend-to-Azure API calls only)

> **Note**: The client secret is used by the backend for Azure API calls (Cost Management, Key Vault, etc.) — NOT for user authentication. User auth uses the implicit/PKCE flow with MSAL.js.

1. Go to **Certificates & secrets** blade → **+ New client secret**
2. Description: `OpsPortal Backend Secret`
3. Expiry: **12 months** (set a calendar reminder to rotate)
4. Click **Add** and **immediately copy** the secret value → this is `AZURE_CLIENT_SECRET`

---

## Step 2: Expose an API (Backend Scope)

This configures the `api://{clientId}/.default` scope that the frontend requests tokens for.

1. Go to **Expose an API** blade
2. Click **Set** next to "Application ID URI" and accept the default: `api://<client-id>`
3. Click **+ Add a scope**:
   - **Scope name**: `access_as_user`
   - **Who can consent**: Admins and users
   - **Admin consent display name**: `Access OpsPortal API`
   - **Admin consent description**: `Allows the app to access OpsPortal API on behalf of the signed-in user`
   - **User consent display name**: `Access OpsPortal`
   - **User consent description**: `Allow OpsPortal to access the API on your behalf`
   - **State**: Enabled
4. Click **Add scope**

> The frontend uses `api://{clientId}/.default` which includes all defined scopes. This matches the code in `authConfig.ts`.

---

## Step 3: Define App Roles (RBAC)

These roles are sent in the JWT `roles` claim and mapped by `_map_roles()` in the backend.

1. Go to **App roles** blade → **+ Create app role** for each role:

| Display Name | Value | Description | Allowed member types |
|---|---|---|---|
| `OpsPortal Admin` | `OpsPortal.Admin` | Full administrative access — manage subscriptions, sync data, manage users | Users/Groups |
| `OpsPortal Write` | `OpsPortal.Write` | Write access — trigger syncs, modify configurations | Users/Groups |
| `OpsPortal Read` | `OpsPortal.Read` | Read-only access — view dashboards and reports | Users/Groups |

2. Click **Create** for each role
3. Verify all three roles appear with **Enabled** status

> These values match exactly with `backend/app/core/config.py`:
> - `ROLE_ADMIN = "OpsPortal.Admin"`
> - `ROLE_WRITE = "OpsPortal.Write"`
> - `ROLE_READ = "OpsPortal.Read"`

---

## Step 4: Configure API Permissions

1. Go to **API permissions** blade
2. Ensure **Microsoft Graph → User.Read** (delegated) is present (added by default)
3. Click **+ Add a permission** → **My APIs** → **OpsPortal**
   - Select **Delegated permissions** → Check `access_as_user`
4. Click **Grant admin consent for \<tenant\>** (requires Global Admin / Privileged Role Admin)

---

## Step 5: Assign Users & Groups to Roles

### 5.1 Via Enterprise Application

1. Go to **Microsoft Entra ID** → **Enterprise applications** → Search for **OpsPortal**
2. Go to **Users and groups** blade → **+ Add user/group**
3. Assign roles following this matrix:

| Team / Group | Role | Justification |
|---|---|---|
| Infra / Ops team | `OpsPortal.Admin` | Full access — manage subscriptions, config, syncs |
| DevOps / SRE leads | `OpsPortal.Write` | Can trigger syncs, view & export all data |
| Dev team | `OpsPortal.Read` | View dashboards only |
| Test / QA team | `OpsPortal.Read` | View dashboards only |
| Management / Leadership | `OpsPortal.Read` | View leadership dashboard & cost reports |

### 5.2 Using Azure AD Groups (Recommended)

For easier management, create security groups and assign roles to groups:

1. Create groups in Entra ID:
   - `SG-OpsPortal-Admins` → assign `OpsPortal.Admin`
   - `SG-OpsPortal-Writers` → assign `OpsPortal.Write`
   - `SG-OpsPortal-Readers` → assign `OpsPortal.Read`
2. Add individual users to the appropriate groups
3. When new team members join, just add them to the group — no per-user role assignment needed

### 5.3 Require Assignment (Recommended)

1. In **Enterprise applications** → **OpsPortal** → **Properties**
2. Set **Assignment required?** = **Yes**
3. This ensures only explicitly assigned users/groups can access the app

---

## Step 6: Configure Conditional Access for MFA (Optional but Recommended)

The frontend code already requests the `acrs` claim with value `c1` for MFA enforcement:

```typescript
// authConfig.ts — already in codebase
claims: JSON.stringify({
  access_token: {
    acrs: { essential: true, values: ["c1"] },
  },
}),
```

### 6.1 Create Authentication Context

1. **Azure Portal** → **Entra ID** → **Security** → **Conditional Access** → **Authentication context**
2. Click **+ New authentication context**
   - **Name**: `MFA Required`
   - **ID**: `c1` (must match the `values: ["c1"]` in the frontend code)
   - **Description**: `Requires multi-factor authentication`
3. Click **Save**

### 6.2 Create Conditional Access Policy

1. **Conditional Access** → **+ New policy**
2. Configure:
   - **Name**: `OpsPortal — Require MFA`
   - **Users**: All users (or target specific groups)
   - **Target resources** → **Authentication context** → Select `c1`
   - **Grant**: **Require multifactor authentication**
   - **Session**: Optionally set sign-in frequency (e.g., 8 hours)
3. **Enable policy**: On
4. Click **Create**

> If you skip this step, Azure AD will still authenticate users but may not enforce MFA unless tenant defaults require it. The app will still work — MFA is an additional security layer.

---

## Step 7: Set Environment Variables

### 7.1 Backend (`.env` or deployment config)

```bash
# ── Authentication ────────────────────────────
ENVIRONMENT=production                              # Change from "development" to enable auth
AZURE_TENANT_ID=e741d71c-c6b6-47b0-803c-0f3b32b07556
AZURE_CLIENT_ID=<your-app-registration-client-id>   # From Step 1.1
AZURE_CLIENT_SECRET=<your-client-secret>             # From Step 1.3

# ── RBAC Role Names (match App Roles in Step 3) ──
# These are already set in config.py defaults:
# ROLE_ADMIN=OpsPortal.Admin
# ROLE_WRITE=OpsPortal.Write
# ROLE_READ=OpsPortal.Read
```

**Critical**: Change `ENVIRONMENT` from `development` to `staging` or `production` to activate JWT validation. In `development` mode, the backend returns a synthetic admin user without checking tokens.

### 7.2 Frontend (`.env` or Vite build-time config)

```bash
# ── MSAL Authentication ──────────────────────
VITE_AZURE_CLIENT_ID=<your-app-registration-client-id>   # Same client ID as backend
VITE_AZURE_TENANT_ID=e741d71c-c6b6-47b0-803c-0f3b32b07556
VITE_REDIRECT_URI=https://opsportal.<your-domain>.com     # Must match Step 1.2
VITE_API_BASE_URL=/api/v1
```

**Critical**: When `VITE_AZURE_CLIENT_ID` and `VITE_AZURE_TENANT_ID` are set to real values, `isDevMode` becomes `false` and MSAL is fully activated — the login page appears and tokens are attached to all API calls.

### 7.3 For AKS/K8s Deployment

Store secrets in Azure Key Vault and inject via `akvtoaks` or External Secrets Operator:

```yaml
# Kubernetes Secret (reference only — use AKV in production)
apiVersion: v1
kind: Secret
metadata:
  name: opsportal-auth
type: Opaque
stringData:
  ENVIRONMENT: "production"
  AZURE_TENANT_ID: "e741d71c-c6b6-47b0-803c-0f3b32b07556"
  AZURE_CLIENT_ID: "<client-id>"
  AZURE_CLIENT_SECRET: "<client-secret>"
```

---

## Step 8: Test the Authentication Flow

### 8.1 Test in Development Mode First

1. Keep `ENVIRONMENT=development` in backend `.env`
2. Do NOT set `VITE_AZURE_CLIENT_ID` / `VITE_AZURE_TENANT_ID` in frontend
3. Verify all pages work with the `DEV MODE` badge visible
4. Backend logs should show: `dev_mode_auth_bypass`

### 8.2 Enable Backend Auth Only

1. Set `ENVIRONMENT=staging` in backend `.env`
2. Set `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` to real values
3. ⚠️ API calls from the frontend (still in dev mode) will now fail with **401 Unauthorized**
4. This confirms backend JWT validation is active

### 8.3 Enable Full Auth (Backend + Frontend)

1. Create `frontend/.env`:
   ```bash
   VITE_AZURE_CLIENT_ID=<your-client-id>
   VITE_AZURE_TENANT_ID=e741d71c-c6b6-47b0-803c-0f3b32b07556
   ```
2. Restart the Vite dev server (`npm run dev`)
3. The app should now show the **"Sign in with Microsoft"** login page
4. After signing in:
   - The navigation bar should show your display name (instead of "Local Developer")
   - The "DEV MODE" badge should be gone
   - The "Sign out" button should appear
5. Check browser DevTools → Network tab:
   - API requests should have `Authorization: Bearer <token>` header
6. Check backend logs:
   - Should show decoded user context with roles

### 8.4 Test Role-Based Access

1. Sign in with a user assigned `OpsPortal.Admin` → should access all pages including Admin
2. Sign in with a user assigned `OpsPortal.Read` → should be able to view dashboards
3. Sign in with a user that has NO role assigned:
   - If "Assignment required" is **Yes** → login is blocked entirely
   - If "Assignment required" is **No** → user gets default `READ` role (via `_map_roles()` fallback)

### 8.5 Test MFA (if Conditional Access configured)

1. Sign in → Azure AD should prompt for a second factor (Authenticator app, SMS, etc.)
2. After MFA, verify the `acrs` claim in the token includes `c1`
3. Silent token renewal (`acquireTokenSilent`) should NOT re-prompt for MFA

---

## Step 9: Endpoint-Role Matrix

Once auth is active, apply `require_role()` to protect endpoints. The dependency is already imported in all endpoint files.

### Recommended Access Control

| Endpoint | Admin | Write | Read | Notes |
|---|:---:|:---:|:---:|---|
| `GET /leadership/*` | ✅ | ✅ | ✅ | Everyone can view leadership dashboard |
| `GET /costs/amortized-summary` | ✅ | ✅ | ✅ | View cost analytics |
| `GET /costs/amortized-drilldown` | ✅ | ✅ | ✅ | View cost detail |
| `POST /costs/amortized/sync` | ✅ | ✅ | ❌ | Trigger data sync from Azure |
| `GET /costs/amortized/sync-status` | ✅ | ✅ | ✅ | View sync status |
| `GET /costs/env-daily/*` | ✅ | ✅ | ✅ | View daily costs |
| `POST /costs/env-daily/sync` | ✅ | ✅ | ❌ | Trigger daily cost sync |
| `GET /optimization/*` | ✅ | ✅ | ✅ | View optimization recommendations |
| `GET /keyvault/*` | ✅ | ✅ | ✅ | View Key Vault status |
| `POST /keyvault/sync` | ✅ | ✅ | ❌ | Trigger KV sync |
| `GET /aks/*` | ✅ | ✅ | ✅ | View AKS operations |
| `POST /aks/*/restart` | ✅ | ❌ | ❌ | AKS pod restarts (admin only) |
| `GET /compliance/*` | ✅ | ✅ | ✅ | View compliance reports |
| `GET /infra-alerts/*` | ✅ | ✅ | ✅ | View infra alerts |
| `GET /admin/*` | ✅ | ❌ | ❌ | Admin dashboard (admin only) |
| `POST /admin/subscriptions` | ✅ | ❌ | ❌ | Manage subscriptions |
| `PUT /admin/subscriptions/*` | ✅ | ❌ | ❌ | Update subscription |
| `DELETE /admin/subscriptions/*` | ✅ | ❌ | ❌ | Delete subscription |

### Example: Apply to an Endpoint

```python
from app.auth import require_role
from app.models.auth import UserRole

# Read-only endpoint — all authenticated users
@router.get("/costs/amortized-summary")
async def get_amortized_summary(
    user: UserContext = Depends(get_current_user),
    # ... other params
):
    ...

# Write endpoint — requires WRITE or ADMIN
@router.post("/costs/amortized/sync")
async def sync_amortized_costs(
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    # ... other params
):
    ...

# Admin-only endpoint
@router.delete("/admin/subscriptions/{id}")
async def delete_subscription(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    # ... other params
):
    ...
```

---

## Step 10: Production Deployment Checklist

- [ ] App Registration created with correct redirect URIs
- [ ] API exposed with `access_as_user` scope
- [ ] Three App Roles defined: `OpsPortal.Admin`, `OpsPortal.Write`, `OpsPortal.Read`
- [ ] Admin consent granted for API permissions
- [ ] Users/Groups assigned to appropriate roles
- [ ] "Assignment required" set to **Yes** on Enterprise Application
- [ ] `ENVIRONMENT` set to `production` (not `development`)
- [ ] `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` set correctly in both backend and frontend
- [ ] `AZURE_CLIENT_SECRET` stored in Azure Key Vault (not in code)
- [ ] `VITE_REDIRECT_URI` matches the production URL
- [ ] Conditional Access policy created (if MFA required)
- [ ] Client secret rotation reminder set (12-month expiry)
- [ ] Tested login flow with at least one user per role
- [ ] Verified logout clears session
- [ ] Verified 401 is returned for unauthenticated requests
- [ ] Verified 403 is returned for insufficient role
- [ ] Frontend hides admin nav items for non-admin users (future enhancement)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        User Browser                         │
│                                                             │
│  ┌─────────────┐     ┌──────────────┐    ┌──────────────┐  │
│  │ React App   │────▶│ MSAL.js      │───▶│ Azure AD     │  │
│  │ (Vite:5177) │◀────│ (PKCE flow)  │◀───│ Login + MFA  │  │
│  └──────┬──────┘     └──────────────┘    └──────────────┘  │
│         │                                                   │
│         │  Authorization: Bearer <JWT>                      │
│         ▼                                                   │
│  ┌──────────────┐                                           │
│  │ Axios Client │                                           │
│  │ (apiClient)  │                                           │
│  └──────┬───────┘                                           │
└─────────┼───────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (:8000)                   │
│                                                             │
│  ┌──────────────────────────────────────────────────┐       │
│  │  HTTPBearer → get_current_user()                  │       │
│  │    │                                              │       │
│  │    ├─ Fetch JWKS (cached) from Azure AD           │       │
│  │    ├─ Validate JWT (RS256, aud, iss, exp)         │       │
│  │    ├─ Extract claims → TokenClaims                │       │
│  │    ├─ Map roles → UserContext                     │       │
│  │    └─ Attach to request.state                     │       │
│  └──────────────────────────────────────────────────┘       │
│                                                             │
│  ┌──────────────────────────────────────────────────┐       │
│  │  require_role(UserRole.ADMIN / WRITE / READ)      │       │
│  │    │                                              │       │
│  │    ├─ Check user.roles against required roles     │       │
│  │    ├─ ADMIN bypasses all role checks              │       │
│  │    └─ 403 Forbidden if insufficient               │       │
│  └──────────────────────────────────────────────────┘       │
│                                                             │
│     Endpoints: /api/v1/costs/*, /admin/*, /aks/*, etc.      │
└─────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Login page doesn't appear | `isDevMode` is `true` | Set `VITE_AZURE_CLIENT_ID` and `VITE_AZURE_TENANT_ID` |
| "AADSTS700016" after login | Wrong client ID or redirect URI | Verify App Registration client ID and redirect URI match |
| "AADSTS50011" redirect mismatch | Redirect URI not registered | Add the exact URI in App Registration → Authentication |
| 401 on all API calls | Token not attached or backend can't validate | Check `Authorization` header in Network tab; verify backend `AZURE_CLIENT_ID` |
| 403 on admin endpoints | User lacks required role | Assign `OpsPortal.Admin` role in Enterprise Application → Users and groups |
| "Unable to find signing key" | JWKS key mismatch | Clear `_jwks_cache` (restart backend); verify tenant ID |
| Silent token fails | Session expired | MSAL auto-redirects to login; verify `acquireTokenRedirect` fallback |
| MFA not prompted | No Conditional Access policy | Create CA policy with authentication context `c1` (Step 6) |

---

## Timeline Estimate

| Phase | Duration | Dependency |
|---|---|---|
| Step 1-4: Azure Portal setup | 1-2 hours | Azure AD admin access |
| Step 5: User/group assignment | 30 min | Team member list |
| Step 6: Conditional Access (MFA) | 30 min | Security team approval |
| Step 7: Environment variables | 15 min | Deployed environments |
| Step 8: Testing | 1-2 hours | All above complete |
| Step 9: Endpoint protection | 2-3 hours | Code changes |
| Step 10: Production checklist | 30 min | All above verified |

**Total**: ~6-8 hours (mostly Azure Portal + testing, minimal code changes needed)

---

*Document generated for OpsPortal — `apm0014313-attcc-ops-portal/azure-ops-portal`*
