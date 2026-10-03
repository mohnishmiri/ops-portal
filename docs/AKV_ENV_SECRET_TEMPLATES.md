# AKV Env Secret Templates

This deployment flow uses one Azure Key Vault secret per `.env` entry.

Flow:

- put the real value for each environment variable into its own secret in Azure Key Vault
- list those AKV secret names in [helm/ops-portal/values.yaml](../helm/ops-portal/values.yaml)
- Helm creates one `AzureKeyVaultSecret` object per mapping
- the akv2k8s controller syncs each mapping into one Kubernetes `Secret`
- the Deployment manifest reads each synced Kubernetes `Secret` with `secretKeyRef`
- optionally map an exportable Azure Key Vault certificate to the ingress TLS secret named in `ingress.tls`

This keeps actual application secrets out of GitHub.

## Actual Step Order

1. Update multiple secrets in Azure Key Vault with the real values.
2. Use those AKV secret names in the Helm values file.
3. Apply the Helm chart.
4. `AzureKeyVaultSecret` objects are created in AKS.
5. akv2k8s syncs AKV secrets into AKS Secrets.
6. Deployments consume the synced AKS Secrets as env values.

## Object Count

Per environment (from `helm/ops-portal/values.yaml`):

- backend AKV secrets: `47` — `17` required, `30` optional (feature-gated: a missing secret falls back to the backend's default instead of blocking pod start)
- frontend AKV secrets: `4`
- ingress TLS certificate: `1` (when `ingress.azureKeyVaultCertificates.enabled`)
- `AzureKeyVaultSecret` objects created in AKS: `52` (one per mapping)
- Kubernetes `Secret` objects created in AKS: `52`

Required secrets must exist in Key Vault before deploying. Create an optional
one only when you use that feature (Ollama advisor, Agent LLM, K8s Dashboard,
Keyfactor).

## Ingress TLS Certificate Mapping

Use `ingress.azureKeyVaultCertificates` when the ingress TLS secret should come from Azure Key Vault instead of cert-manager.

Example values:

```yaml
ingress:
  annotations: {}
  azureKeyVaultCertificates:
    enabled: true
    vaultName: my-shared-kv
    items:
      - akvCertificateName: opsportal-ingress-tls
        kubernetesSecretName: ops-portal-tls
        chainOrder: ensureserverfirst
  tls:
    - secretName: ops-portal-tls
      hosts:
        - attccopsportal.stage.att.com
```

Notes:

- the Azure Key Vault certificate must be exportable so akv2k8s can populate both `tls.crt` and `tls.key`
- `kubernetesSecretName` must match the ingress `tls[].secretName`
- remove or override `cert-manager.io/cluster-issuer` when akv2k8s owns the TLS secret

## Backend Secret Mapping

| Env Var | AKV Secret Name | AKS Secret Name | |
|---|---|---|---|
| `ENVIRONMENT` | `opsportal-backend-environment` | `ops-portal-backend-environment` | **Required** |
| `LOG_LEVEL` | `opsportal-backend-log-level` | `ops-portal-backend-log-level` | **Required** |
| `AZURE_TENANT_ID` | `opsportal-backend-azure-tenant-id` | `ops-portal-backend-azure-tenant-id` | **Required** |
| `AZURE_CLIENT_ID` | `opsportal-backend-azure-client-id` | `ops-portal-backend-azure-client-id` | **Required** |
| `AZURE_CLIENT_SECRET` | `opsportal-backend-azure-client-secret` | `ops-portal-backend-azure-client-secret` | **Required** |
| `AZURE_SUBSCRIPTION_IDS` | `opsportal-backend-azure-subscription-ids` | `ops-portal-backend-azure-subscription-ids` | **Required** |
| `DATABASE_URL` | `opsportal-backend-database-url` | `ops-portal-backend-database-url` | **Required** |
| `DB_ECHO` | `opsportal-backend-db-echo` | `ops-portal-backend-db-echo` | **Required** |
| `SMTP_HOST` | `opsportal-backend-smtp-host` | `ops-portal-backend-smtp-host` | **Required** |
| `SMTP_PORT` | `opsportal-backend-smtp-port` | `ops-portal-backend-smtp-port` | **Required** |
| `SMTP_USER` | `opsportal-backend-smtp-user` | `ops-portal-backend-smtp-user` | **Required** |
| `SMTP_PASSWORD` | `opsportal-backend-smtp-password` | `ops-portal-backend-smtp-password` | **Required** |
| `SMTP_FROM_ADDRESS` | `opsportal-backend-smtp-from-address` | `ops-portal-backend-smtp-from-address` | **Required** |
| `SMTP_USE_TLS` | `opsportal-backend-smtp-use-tls` | `ops-portal-backend-smtp-use-tls` | **Required** |
| `KEYVAULT_URL` | `opsportal-backend-keyvault-url` | `ops-portal-backend-keyvault-url` | **Required** |
| `CORS_ORIGINS` | `opsportal-backend-cors-origins` | `ops-portal-backend-cors-origins` | **Required** |
| `RATE_LIMIT_RPM` | `opsportal-backend-rate-limit-rpm` | `ops-portal-backend-rate-limit-rpm` | **Required** |
| `OLLAMA_BASE_URL` | `opsportal-backend-ollama-base-url` | `ops-portal-backend-ollama-base-url` | Optional |
| `OLLAMA_MODEL` | `opsportal-backend-ollama-model` | `ops-portal-backend-ollama-model` | Optional |
| `OLLAMA_TIMEOUT_SECONDS` | `opsportal-backend-ollama-timeout-seconds` | `ops-portal-backend-ollama-timeout-seconds` | Optional |
| `OLLAMA_AUTH_HEADER_NAME` | `opsportal-backend-ollama-auth-header-name` | `ops-portal-backend-ollama-auth-header-name` | Optional |
| `OLLAMA_AUTH_HEADER_VALUE` | `opsportal-backend-ollama-auth-header-value` | `ops-portal-backend-ollama-auth-header-value` | Optional |
| `AGENT_LLM_BASE_URL` | `opsportal-backend-agent-llm-base-url` | `ops-portal-backend-agent-llm-base-url` | Optional |
| `AGENT_LLM_MODEL` | `opsportal-backend-agent-llm-model` | `ops-portal-backend-agent-llm-model` | Optional |
| `AGENT_LLM_TIMEOUT_SECONDS` | `opsportal-backend-agent-llm-timeout-seconds` | `ops-portal-backend-agent-llm-timeout-seconds` | Optional |
| `AGENT_LLM_AUTH_HEADER_NAME` | `opsportal-backend-agent-llm-auth-header-name` | `ops-portal-backend-agent-llm-auth-header-name` | Optional |
| `AGENT_LLM_AUTH_HEADER_VALUE` | `opsportal-backend-agent-llm-auth-header-value` | `ops-portal-backend-agent-llm-auth-header-value` | Optional |
| `K8S_DASHBOARD_TOKEN_PROD` | `opsportal-backend-k8s-dashboard-token-prod` | `ops-portal-backend-k8s-dashboard-token-prod` | Optional |
| `K8S_DASHBOARD_TOKEN_PREPROD` | `opsportal-backend-k8s-dashboard-token-preprod` | `ops-portal-backend-k8s-dashboard-token-preprod` | Optional |
| `K8S_DASHBOARD_TOKEN_PERF` | `opsportal-backend-k8s-dashboard-token-perf` | `ops-portal-backend-k8s-dashboard-token-perf` | Optional |
| `K8S_DASHBOARD_TOKEN_UAT` | `opsportal-backend-k8s-dashboard-token-uat` | `ops-portal-backend-k8s-dashboard-token-uat` | Optional |
| `K8S_DASHBOARD_TOKEN_DEV` | `opsportal-backend-k8s-dashboard-token-dev` | `ops-portal-backend-k8s-dashboard-token-dev` | Optional |
| `K8S_DASHBOARD_TOKEN_DR` | `opsportal-backend-k8s-dashboard-token-dr` | `ops-portal-backend-k8s-dashboard-token-dr` | Optional |
| `K8S_DASHBOARD_SESSION_SECRET` | `opsportal-backend-k8s-dashboard-session-secret` | `ops-portal-backend-k8s-dashboard-session-secret` | Optional |
| `KEYFACTOR_BASE_URL` | `opsportal-backend-keyfactor-base-url` | `ops-portal-backend-keyfactor-base-url` | Optional |
| `KEYFACTOR_TENANT_ID` | `opsportal-backend-keyfactor-tenant-id` | `ops-portal-backend-keyfactor-tenant-id` | Optional |
| `KEYFACTOR_CLIENT_ID` | `opsportal-backend-keyfactor-client-id` | `ops-portal-backend-keyfactor-client-id` | Optional |
| `KEYFACTOR_CLIENT_SECRET` | `opsportal-backend-keyfactor-client-secret` | `ops-portal-backend-keyfactor-client-secret` | Optional |
| `KEYFACTOR_OAUTH_SCOPE` | `opsportal-backend-keyfactor-oauth-scope` | `ops-portal-backend-keyfactor-oauth-scope` | Optional |
| `KEYFACTOR_API_VERSION` | `opsportal-backend-keyfactor-api-version` | `ops-portal-backend-keyfactor-api-version` | Optional |
| `KEYFACTOR_TIMEOUT_SECONDS` | `opsportal-backend-keyfactor-timeout-seconds` | `ops-portal-backend-keyfactor-timeout-seconds` | Optional |
| `KEYFACTOR_VERIFY_SSL` | `opsportal-backend-keyfactor-verify-ssl` | `ops-portal-backend-keyfactor-verify-ssl` | Optional |
| `KEYFACTOR_DEFAULT_CA` | `opsportal-backend-keyfactor-default-ca` | `ops-portal-backend-keyfactor-default-ca` | Optional |
| `KEYFACTOR_DEFAULT_TEMPLATE` | `opsportal-backend-keyfactor-default-template` | `ops-portal-backend-keyfactor-default-template` | Optional |
| `KEYFACTOR_ENROLLMENT_PATTERNS` | `opsportal-backend-keyfactor-enrollment-patterns` | `ops-portal-backend-keyfactor-enrollment-patterns` | Optional |
| `KEYFACTOR_TOKEN_URL` | `opsportal-backend-keyfactor-token-url` | `ops-portal-backend-keyfactor-token-url` | Optional |
| `KEYFACTOR_CA_BUNDLE` | `opsportal-backend-keyfactor-ca-bundle` | `ops-portal-backend-keyfactor-ca-bundle` | Optional |

## Backend Plain Settings (no Key Vault secret)

Non-secret settings are set directly under `backend.env` in the Helm values.
Per-environment overrides go in `values-dev.yaml` / `values-prod.yaml`. A key
set here wins over a Key Vault secret of the same name. Defaults in
`values.yaml`:

| Env Var | Default |
|---|---|
| `CERT_KEY_ESCROW_ENABLED` | `false` |
| `CERT_KEY_ESCROW_VAULT` | `` |
| `CERT_KEY_ESCROW_VAULT_URI` | `` |
| `ROLE_SUPER_ADMIN` | `OpsPortal.SuperAdmin` |
| `ROLE_ADMIN` | `OpsPortal.Admin` |
| `ROLE_WRITE` | `OpsPortal.Write` |
| `ROLE_READ` | `OpsPortal.Read` |
| `DEBUG` | `false` |
| `DEV_AUTH_BYPASS` | `false` |
| `NOTIFICATION_RECIPIENTS` | `["ARISTOS-AO-EUGENE-COMM-INFRA@accenture.com"]` |
| `DB_POOL_SIZE` | `100` |
| `DB_MAX_OVERFLOW` | `50` |
| `DB_POOL_RECYCLE` | `1800` |
| `DB_POOL_TIMEOUT` | `30` |
| `CACHE_TTL_SECONDS` | `3600` |
| `REPORT_CACHE_TTL` | `86400` |
| `K8S_DASHBOARD_PROXY_TIMEOUT` | `30` |
| `KEYFACTOR_LIST_CACHE_TTL` | `60` |
| `AZURE_PRICING_API_URL` | `https://prices.azure.com/api/retail/prices` |
| `AZURE_PRICING_TIMEOUT_SECONDS` | `10` |
| `AZURE_PRICING_CURRENCY_CODE` | `USD` |
| `AZURE_AUTHORITY` | `` |

`PORTAL_BASE_URL` (links in access-request and alert emails) is not listed
because the chart derives it. It defaults to `https://<first ingress host>`,
which CI sets from the `DEV_HOSTNAME` / `PROD_HOSTNAME` secrets. Set
`backend.env.PORTAL_BASE_URL` only if the public URL differs. `values-dev.yaml`
sets it explicitly to the stage URL.

Certificate escrow per environment: stage enables it with
`CERT_KEY_ESCROW_VAULT: attcc-eastus2-stge-kv`; prod keeps it off until PKI
sign-off (see [CERTIFICATE_MANAGEMENT.md](CERTIFICATE_MANAGEMENT.md)).

## Frontend Secret Mapping

| Env Var | AKV Secret Name | AKS Secret Name |
|---|---|---|
| `VITE_AZURE_CLIENT_ID` | `opsportal-frontend-azure-client-id` | `ops-portal-frontend-azure-client-id` |
| `VITE_AZURE_TENANT_ID` | `opsportal-frontend-azure-tenant-id` | `ops-portal-frontend-azure-tenant-id` |
| `VITE_REDIRECT_URI` | `opsportal-frontend-redirect-uri` | `ops-portal-frontend-redirect-uri` |
| `VITE_API_BASE_URL` | `opsportal-frontend-api-base-url` | `ops-portal-frontend-api-base-url` |

## Verification

```bash
kubectl -n opsportal get azurekeyvaultsecret
kubectl -n opsportal get secret | grep '^ops-portal-backend-\|^ops-portal-frontend-'
kubectl -n opsportal describe azurekeyvaultsecret ops-portal-backend-database-url-sync
kubectl -n opsportal get secret ops-portal-backend-database-url -o yaml
kubectl -n opsportal exec deploy/ops-portal-backend -- sh -lc 'printenv DATABASE_URL >/dev/null && echo DATABASE_URL_PRESENT'
kubectl -n opsportal exec deploy/ops-portal-frontend -- sh -lc 'printenv VITE_API_BASE_URL >/dev/null && echo VITE_API_BASE_URL_PRESENT'
kubectl -n opsportal describe azurekeyvaultsecret ops-portal-tls-sync
kubectl -n opsportal get secret ops-portal-tls -o yaml
```

## Troubleshooting

- verify the `spv.no/v2beta1` CRD exists
- verify akv2k8s is healthy
- verify the Key Vault name is correct
- verify each AKV secret exists exactly as listed in the Helm values file
- verify the identity used by akv2k8s can read those Key Vault secrets
- verify the Deployment `secretKeyRef` names and keys match the synced AKS secret names and env var names exactly

Frontend note:

- `VITE_*` values are still public browser configuration even if they originate in Key Vault