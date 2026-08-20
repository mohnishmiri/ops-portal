# Certificate Management (Keyfactor Command)

Production-grade certificate lifecycle management for the Ops-Portal, integrated
with **Keyfactor Command** via its REST API. Provides list/search, view, enroll
(CSR & PFX), renew, revoke, update-metadata, and delete operations through both
the API and UI, with RBAC gating and full audit logging.

---

## 1. Overview & Architecture

```
Browser (React)                Ops-Portal Backend (FastAPI)              Azure AD           Keyfactor Command
────────────────               ────────────────────────────            ─────────          ──────────────────
CertificatesPage        ──▶    /api/v1/certificates/*            ──▶    OAuth2 token   ──▶  /KeyfactorAPI/*
  certificatesApi.ts             certificates.py (router)                (client creds)      Certificates,
  React Query hooks              keyfactor_service.py (logic)      ◀──   bearer token        Enrollment, Revoke,
  MSAL id-token                  keyfactor_client.py (HTTP)        ─────────────────────▶    Metadata
                                 audit_logs (Postgres)
```

- **Frontend** ([frontend/src/pages/CertificatesPage.tsx](../frontend/src/pages/CertificatesPage.tsx))
  renders a searchable/filterable table with per-row lifecycle actions and modal
  dialogs. Server state is managed with React Query via
  [frontend/src/services/certificatesApi.ts](../frontend/src/services/certificatesApi.ts).
- **Backend router**
  ([backend/app/api/v1/endpoints/certificates.py](../backend/app/api/v1/endpoints/certificates.py))
  is thin: it validates input, enforces RBAC, calls the service, and writes audit rows.
- **Service layer**
  ([backend/app/services/keyfactor_service.py](../backend/app/services/keyfactor_service.py))
  validates, normalizes Keyfactor responses to a stable schema, computes a derived
  status, and maps upstream errors to friendly messages.
- **Client layer**
  ([backend/app/services/keyfactor_client.py](../backend/app/services/keyfactor_client.py))
  handles Azure AD token acquisition (client-credentials), caching/refresh,
  401 re-auth, timeouts, and a single retry with backoff.

### Data flow (enroll example)

1. User submits the Enroll modal → `POST /api/v1/certificates/enroll`.
2. Router checks the `WRITE` role, validates the payload.
3. Service builds the Keyfactor payload and calls the client.
4. Client acquires (or reuses) an Azure AD bearer token and calls Keyfactor.
5. Result is shaped (PFX/private-key returned once, never stored/logged) and returned.
6. An audit row is written to `audit_logs`.

---

## 2. Prerequisites & Setup

### Azure Service Principal

Create (or reuse) an Azure AD **App Registration / service principal** that is
authorized to call the Keyfactor Command API:

- Grant it the API permission/scope exposed by the Keyfactor app registration
  (e.g. `api://<keyfactor-app-id>/.default`).
- Create a client secret (store it in Azure Key Vault / environment — never in code).

### Keyfactor Command

- A Keyfactor **security role** mapped to the service principal, granting the
  needed permissions: certificate read, enrollment, revocation, metadata edit,
  and delete.
- One or more **certificate templates** and **issuing CAs** the portal may use.

### Configuration keys

All keys live in [backend/app/core/config.py](../backend/app/core/config.py) and are
read from environment variables / `.env` / Key Vault.

| Key | Required | Description |
| --- | --- | --- |
| `KEYFACTOR_BASE_URL` | Yes | Base URL of the Keyfactor Command instance (e.g. `https://keyfactor.example.com`). |
| `KEYFACTOR_CLIENT_ID` | Yes | Client ID of the Azure AD service principal used for Keyfactor tokens. |
| `KEYFACTOR_CLIENT_SECRET` | Yes | Client secret for that service principal. |
| `KEYFACTOR_OAUTH_SCOPE` | Yes | OAuth2 scope/resource for the Keyfactor API (e.g. `api://<app-id>/.default`). |
| `KEYFACTOR_TENANT_ID` | No | Azure AD tenant ID (defaults to `AZURE_TENANT_ID`). |
| `KEYFACTOR_TOKEN_URL` | No | Explicit token endpoint (defaults to the tenant v2.0 token endpoint). |
| `KEYFACTOR_API_VERSION` | No | Value for the `x-keyfactor-api-version` header (default `1`). |
| `KEYFACTOR_TIMEOUT_SECONDS` | No | Request timeout (default `30`). |
| `KEYFACTOR_VERIFY_SSL` | No | Verify TLS certificates when calling Keyfactor (default `true`). |
| `KEYFACTOR_DEFAULT_CA` | No | Optional default issuing CA to pre-fill enrollment. |
| `KEYFACTOR_DEFAULT_TEMPLATE` | No | Optional default template to pre-fill enrollment. |
| `KEYFACTOR_LIST_CACHE_TTL` | No | Reserved for short-lived list caching (default `60`). |

---

## 3. API Reference

Base path: `/api/v1/certificates`. All endpoints require an authenticated user.

| Method | Path | Role | Description |
| --- | --- | --- | --- |
| `GET` | `/` | view | List/search certificates (paginated & filterable). |
| `GET` | `/{id}` | view | Full metadata for one certificate. |
| `POST` | `/enroll` | WRITE | Enroll a new certificate (CSR or PFX). |
| `POST` | `/{id}/renew` | WRITE | Renew an existing certificate. |
| `POST` | `/{id}/revoke` | ADMIN | Revoke a certificate with an RFC 5280 reason. |
| `PUT` | `/{id}/metadata` | WRITE | Update metadata / custom fields. |
| `DELETE` | `/{id}` | ADMIN | Delete a certificate record. |

### List / search

`GET /api/v1/certificates?cn=&thumbprint=&issuer=&cert_status=&expires_in_days=&q=&page=1&page_size=25`

Response:

```json
{
  "items": [
    {
      "id": 123,
      "common_name": "app.example.com",
      "subject_dn": "CN=app.example.com",
      "issuer_dn": "CN=Corp Issuing CA",
      "serial_number": "1A2B…",
      "thumbprint": "ABCDEF…",
      "template": "WebServer",
      "certificate_authority": "corp-ca",
      "not_before": "2026-01-01T00:00:00+00:00",
      "not_after": "2027-01-01T00:00:00+00:00",
      "sans": ["app.example.com"],
      "revoked": false,
      "revocation_reason": null,
      "status": "valid",
      "metadata": {}
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 25
}
```

`status` is one of `valid`, `expiring_soon` (≤ 30 days), `expired`, `revoked`, `unknown`.

### Enroll

`POST /api/v1/certificates/enroll`

CSR enrollment:

```json
{
  "enrollment_type": "csr",
  "certificate_authority": "corp-ca",
  "template": "WebServer",
  "csr": "-----BEGIN CERTIFICATE REQUEST-----…",
  "sans": { "dns": ["app.example.com"] },
  "include_chain": true
}
```

PFX enrollment:

```json
{
  "enrollment_type": "pfx",
  "certificate_authority": "corp-ca",
  "template": "WebServer",
  "subject": "CN=app.example.com,O=AT&T",
  "password": "<pfx-password>",
  "key_type": "RSA",
  "key_length": 2048
}
```

The PFX response includes `pfx_base64` **once**. It is streamed to the browser for
a one-time download and is never persisted or logged by the portal.

### Revoke

`POST /api/v1/certificates/{id}/revoke`

```json
{ "reason": "keyCompromise", "comment": "key exposed", "effective_date": null }
```

Allowed `reason` values (RFC 5280): `unspecified`, `keyCompromise`, `caCompromise`,
`affiliationChanged`, `superseded`, `cessationOfOperation`, `certificateHold`,
`removeFromCRL`, `privilegeWithdrawn`, `aaCompromise`.

### Error codes

| Status | Meaning |
| --- | --- |
| `200` / `201` | Success. |
| `403` | Caller lacks the required role. |
| `404` | Certificate not found. |
| `422` | Validation failed (bad input or invalid reason). |
| `502` | Upstream Keyfactor/Azure AD error (auth, timeout, or 5xx). Details are sanitized. |

---

## 4. RBAC / Permission Matrix

Roles come from the existing Ops-Portal authorization model (`admin` / `write` /
`read`). Admin implicitly satisfies every requirement.

| Operation | read | write | admin |
| --- | :---: | :---: | :---: |
| List / Search | ✅ | ✅ | ✅ |
| View details | ✅ | ✅ | ✅ |
| Enroll | ❌ | ✅ | ✅ |
| Renew | ❌ | ✅ | ✅ |
| Update metadata | ❌ | ✅ | ✅ |
| Revoke | ❌ | ❌ | ✅ |
| Delete | ❌ | ❌ | ✅ |

The module/page resources (`certificates`, `certificates_main`) are seeded in
[backend/app/core/resource_registry.py](../backend/app/core/resource_registry.py); the
UI hides write and destructive actions based on the caller's effective permissions.

---

## 5. Usage Guide

1. Open **Certificates** in the top navigation.
2. Filter by common name, thumbprint, or issuer and press **Search**. Status badges
   show valid / expiring soon / expired / revoked.
3. **View** shows full metadata for a certificate.
4. **Enroll Certificate** (write) issues a new certificate via CSR or PFX. For PFX,
   download the returned `.pfx` immediately and store it securely.
5. **Renew** (write) reissues from the same template.
6. **Edit** (write) updates metadata / custom fields.
7. **Revoke** (admin) requires selecting a reason and typing `REVOKE` to confirm.
8. **Delete** (admin) requires typing `DELETE` to confirm.

All write operations are recorded in the audit log (who, what, when, target, outcome).

---

## 6. Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| `502` on every operation | Keyfactor not reachable or auth misconfigured | Verify `KEYFACTOR_BASE_URL`, network/proxy, and `KEYFACTOR_VERIFY_SSL`. |
| "Keyfactor authentication is not configured" | Missing SP config | Set `KEYFACTOR_CLIENT_ID`, `KEYFACTOR_CLIENT_SECRET`, `KEYFACTOR_OAUTH_SCOPE`. |
| Repeated `502` with auth errors | Wrong scope or expired secret | Confirm the scope matches the Keyfactor app registration; rotate the client secret. |
| Token expiry mid-session | Normal — handled automatically | The client re-acquires the token once on a 401 and retries. |
| `403` in the UI | Caller lacks the role | Grant the `write` (enroll/renew/update) or `admin` (revoke/delete) permission. |
| `422` on enroll | Missing required fields | CSR enrollment needs `csr`; PFX needs `subject` and `password`. |
| `404` on view/renew | Certificate id not in Keyfactor | Refresh the list; the record may have been deleted. |

---

## 7. Related Files

- Backend client: [backend/app/services/keyfactor_client.py](../backend/app/services/keyfactor_client.py)
- Backend service: [backend/app/services/keyfactor_service.py](../backend/app/services/keyfactor_service.py)
- Backend router: [backend/app/api/v1/endpoints/certificates.py](../backend/app/api/v1/endpoints/certificates.py)
- Config: [backend/app/core/config.py](../backend/app/core/config.py)
- Frontend service: [frontend/src/services/certificatesApi.ts](../frontend/src/services/certificatesApi.ts)
- Frontend page: [frontend/src/pages/CertificatesPage.tsx](../frontend/src/pages/CertificatesPage.tsx)
- Frontend modals: [frontend/src/features/certificates/](../frontend/src/features/certificates/)
- Tests: `backend/tests/test_keyfactor_client.py`, `backend/tests/test_keyfactor_service.py`,
  `backend/tests/test_certificates_api.py`, `frontend/src/pages/CertificatesPage.test.tsx`,
  `frontend/src/features/certificates/*.test.tsx`
