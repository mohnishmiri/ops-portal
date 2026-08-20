# AKV Env Secret Templates

This deployment flow uses one Azure Key Vault secret per `.env` entry.

Flow:

- put the real value for each environment variable into its own secret in Azure Key Vault
- list those AKV secret names in [helm/ops-portal/values.yaml](h:/ATTCC/GITHUB/apm0014313-attcc-ops-portal/helm/ops-portal/values.yaml)
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

Per environment:

- backend AKV secrets to create: `23`
- frontend AKV secrets to create: `4`
- total AKV secrets to create: `27`
- `AzureKeyVaultSecret` objects created in AKS: `22`
- Kubernetes `Secret` objects created in AKS: `22`

Across both `dev` and `prod`:

- total AKV secrets to create: `54`
- if `dev` and `prod` are separate AKS clusters, total `AzureKeyVaultSecret` objects: `44`
- if `dev` and `prod` are separate AKS clusters, total Kubernetes `Secret` objects: `44`

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

| Env Var | AKV Secret Name | AKS Secret Name |
|---|---|---|
| `ENVIRONMENT` | `opsportal-backend-environment` | `ops-portal-backend-environment` |
| `LOG_LEVEL` | `opsportal-backend-log-level` | `ops-portal-backend-log-level` |
| `AZURE_TENANT_ID` | `opsportal-backend-azure-tenant-id` | `ops-portal-backend-azure-tenant-id` |
| `AZURE_CLIENT_ID` | `opsportal-backend-azure-client-id` | `ops-portal-backend-azure-client-id` |
| `AZURE_CLIENT_SECRET` | `opsportal-backend-azure-client-secret` | `ops-portal-backend-azure-client-secret` |
| `AZURE_SUBSCRIPTION_IDS` | `opsportal-backend-azure-subscription-ids` | `ops-portal-backend-azure-subscription-ids` |
| `REDIS_URL` | `opsportal-backend-redis-url` | `ops-portal-backend-redis-url` |
| `DATABASE_URL` | `opsportal-backend-database-url` | `ops-portal-backend-database-url` |
| `DB_ECHO` | `opsportal-backend-db-echo` | `ops-portal-backend-db-echo` |
| `SMTP_HOST` | `opsportal-backend-smtp-host` | `ops-portal-backend-smtp-host` |
| `SMTP_PORT` | `opsportal-backend-smtp-port` | `ops-portal-backend-smtp-port` |
| `SMTP_USER` | `opsportal-backend-smtp-user` | `ops-portal-backend-smtp-user` |
| `SMTP_PASSWORD` | `opsportal-backend-smtp-password` | `ops-portal-backend-smtp-password` |
| `SMTP_FROM_ADDRESS` | `opsportal-backend-smtp-from-address` | `ops-portal-backend-smtp-from-address` |
| `SMTP_USE_TLS` | `opsportal-backend-smtp-use-tls` | `ops-portal-backend-smtp-use-tls` |
| `KEYVAULT_URL` | `opsportal-backend-keyvault-url` | `ops-portal-backend-keyvault-url` |
| `CORS_ORIGINS` | `opsportal-backend-cors-origins` | `ops-portal-backend-cors-origins` |
| `RATE_LIMIT_RPM` | `opsportal-backend-rate-limit-rpm` | `ops-portal-backend-rate-limit-rpm` |
| `OLLAMA_BASE_URL` | `opsportal-backend-ollama-base-url` | `ops-portal-backend-ollama-base-url` |
| `OLLAMA_MODEL` | `opsportal-backend-ollama-model` | `ops-portal-backend-ollama-model` |
| `OLLAMA_TIMEOUT_SECONDS` | `opsportal-backend-ollama-timeout-seconds` | `ops-portal-backend-ollama-timeout-seconds` |
| `OLLAMA_AUTH_HEADER_NAME` | `opsportal-backend-ollama-auth-header-name` | `ops-portal-backend-ollama-auth-header-name` |
| `OLLAMA_AUTH_HEADER_VALUE` | `opsportal-backend-ollama-auth-header-value` | `ops-portal-backend-ollama-auth-header-value` |

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