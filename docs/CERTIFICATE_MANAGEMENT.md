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
| `CERT_KEY_ESCROW_ENABLED` | No | Capture issuance-time PFX material for later AKV loads (default `false`). |
| `CERT_KEY_ESCROW_VAULT` | No | Name of the dedicated escrow Key Vault. Required when escrow is enabled. |
| `CERT_KEY_ESCROW_VAULT_URI` | No | Full escrow vault URI; overrides `CERT_KEY_ESCROW_VAULT` (sovereign clouds). |

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

## 6. Private-Key Escrow (multi-vault loads)

### The problem it solves

Keyfactor releases a certificate's PFX **only in the enrollment/renewal
response** ([keyfactor_service.py](../backend/app/services/keyfactor_service.py) —
`_shape_enrollment`). Unless key archival is enabled on the template, a later
export fails, which means an un-escrowed certificate can be loaded into exactly
one Key Vault and never again. That blocks the common case of a multi-SAN
certificate whose hostnames span environments, with one vault per environment
(e.g. the same thumbprint in `attcc-eastus2-perf-kv` and `attcc-eastus2-uat-kv`
under different entry names).

With escrow enabled, that one-time PFX is kept, so **Load to AKV works any number
of times, into any vault, long after issuance**.

### Where the key lives

| Store | Holds |
| --- | --- |
| Escrow Key Vault secret (`cert-pfx-<thumbprint>`) | The PFX and its password, as one JSON envelope |
| PostgreSQL `cert_key_escrow` | Vault name, secret name, thumbprint, expiry — **no key material** |

Key material never touches PostgreSQL, so database dumps, replicas and PITR
snapshots stay free of private keys, and the secret inherits HSM-backed storage,
RBAC, soft-delete/purge protection and Azure's access audit trail. Co-locating
the PFX password with the PFX is deliberate: the vault's access control is the
control, and a password nobody recorded is useless months later during an
incident.

### Setup

1. Create a **dedicated** Key Vault, separate from the vaults certificates are
   deployed into, with soft-delete and purge protection enabled.
2. Grant the portal's identity `secrets: get/set/delete` on that vault **only**.
3. Set `CERT_KEY_ESCROW_ENABLED=true` and `CERT_KEY_ESCROW_VAULT=<vault-name>`.
4. Apply [migrations/add_cert_key_escrow.sql](../backend/migrations/add_cert_key_escrow.sql)
   if your deployment manages schema out of band (otherwise it is created at startup).

> Key escrow for internal PKI is a policy decision. Get PKI/security sign-off
> before enabling it.

### Coverage and limits

- **Covered:** every certificate enrolled (PFX) or renewed (PFX mode) through the
  portal *after* escrow is enabled.
- **Not covered — pre-existing certificates.** Their key was never captured and
  Keyfactor will not re-release it. One PFX-mode renewal through the portal
  escrows the key, but issues a new thumbprint, so every vault holding the old
  certificate needs a re-import.
- **Not covered — renewals done outside the portal** (directly in Keyfactor or
  other automation). The grid's `Key` column shows `No key` for these so the gap
  is visible before someone needs the key, not during an incident.
- **CSR enrollment has nothing to escrow** — the key never leaves the requester.
- **Auto-renewal does not seed escrow.** The Auto-Renewal tab records schedules
  and counts due certificates; it does not execute renewals. If it is ever made
  to renew, it must route through the same capture point.

### Lifecycle

| Stage | Behaviour |
| --- | --- |
| Capture | `_escrow_issued_key` in the enroll/renew endpoints; best-effort, so an escrow failure never fails an issuance |
| Use | `Load to AKV` → **Use escrowed key** (preselected when available). `key_source=escrow` fails rather than silently falling back to a Keyfactor export |
| Reconcile | After each full sync: expiry/common-name backfilled from the snapshot |
| Purge | Secrets for expired certificates are deleted and the row marked `purged_at`. A row with unknown expiry is never purged |

---

## 7. Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| `502` on every operation | Keyfactor not reachable or auth misconfigured | Verify `KEYFACTOR_BASE_URL`, network/proxy, and `KEYFACTOR_VERIFY_SSL`. |
| "Keyfactor authentication is not configured" | Missing SP config | Set `KEYFACTOR_CLIENT_ID`, `KEYFACTOR_CLIENT_SECRET`, `KEYFACTOR_OAUTH_SCOPE`. |
| Repeated `502` with auth errors | Wrong scope or expired secret | Confirm the scope matches the Keyfactor app registration; rotate the client secret. |
| Token expiry mid-session | Normal — handled automatically | The client re-acquires the token once on a 401 and retries. |
| `403` in the UI | Caller lacks the role | Grant the `write` (enroll/renew/update) or `admin` (revoke/delete) permission. |
| `422` on enroll | Missing required fields | CSR enrollment needs `csr`; PFX needs `subject` and `password`. |
| `404` on view/renew | Certificate id not in Keyfactor | Refresh the list; the record may have been deleted. |
| `409` "No escrowed private key" | Certificate predates escrow, or was renewed outside the portal | Renew it through the portal to escrow a key, or retry with `key_source=auto` to attempt a live export. |
| `Key` column missing from the grid | Escrow not configured | Set `CERT_KEY_ESCROW_ENABLED` / `CERT_KEY_ESCROW_VAULT`; the flag is omitted entirely when escrow is off. |
| Escrow silently not happening | Vault write refused | Check `cert_escrow_vault_write_failed` in the logs and the identity's `secrets/set` permission on the escrow vault. |

---

## 8. Related Files

- Backend client: [backend/app/services/keyfactor_client.py](../backend/app/services/keyfactor_client.py)
- Backend service: [backend/app/services/keyfactor_service.py](../backend/app/services/keyfactor_service.py)
- Key escrow: [backend/app/services/certificate_escrow_service.py](../backend/app/services/certificate_escrow_service.py)
- Backend router: [backend/app/api/v1/endpoints/certificates.py](../backend/app/api/v1/endpoints/certificates.py)
- Config: [backend/app/core/config.py](../backend/app/core/config.py)
- Frontend service: [frontend/src/services/certificatesApi.ts](../frontend/src/services/certificatesApi.ts)
- Frontend page: [frontend/src/pages/CertificatesPage.tsx](../frontend/src/pages/CertificatesPage.tsx)
- Frontend modals: [frontend/src/features/certificates/](../frontend/src/features/certificates/)
- Tests: `backend/tests/test_keyfactor_client.py`, `backend/tests/test_keyfactor_service.py`,
  `backend/tests/test_certificates_api.py`, `backend/tests/test_certificate_escrow_service.py`,
  `frontend/src/pages/CertificatesPage.test.tsx`,
  `frontend/src/features/certificates/*.test.tsx`
