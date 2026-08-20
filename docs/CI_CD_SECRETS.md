# CI/CD Environment Variables & Secrets

> Required GitHub Actions secrets for the Ops Portal CI/CD pipeline (`.github/workflows/ci-cd.yaml`).

---

## How to Add

Navigate to **GitHub → Repository Settings → Secrets and variables → Actions** and add each secret listed below. For environment-scoped secrets (marked with 🔒), create them under the **dev** or **prod** environment respectively.

---

## Repository-Level Secrets (All Jobs)

| Secret Name | Purpose | Sample Value |
|---|---|---|
| `JFROG_USERNAME` | JFrog Artifactory username for Docker registry login and Python/UV package index authentication | `svc-attcc-ci` |
| `JFROG_PASSWORD` | JFrog Artifactory password/token for registry and PyPI index auth | `AKCp8kxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `AUTH_NPM_TOKEN` | NPM auth token for private `@att` scoped packages during frontend Docker build | `npm_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345` |

---

## Azure / AKS Secrets (Deploy Jobs)

These are used by the `deploy-dev` and `deploy-production` jobs. They can be scoped per environment.

| Secret Name | Purpose | Sample Value |
|---|---|---|
| `AZURE_CLIENT_ID` | Azure AD app registration (service principal) client ID for OIDC / workload identity login | `12345678-abcd-1234-abcd-1234567890ab` |
| `AZURE_TENANT_ID` | Azure AD tenant ID | `87654321-dcba-4321-dcba-ba0987654321` |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID containing the AKS cluster and Key Vault | `aaaabbbb-cccc-dddd-eeee-ffffgggghhh0` |
| `AZURE_CLIENT_SECRET` | 🔒 **Production only** — Service principal client secret for `kubelogin` SPN mode | `xYz~AbCdEfGhIjKlMnOpQrStUvWx.012345` |
| `AKS_RESOURCE_GROUP` | Resource group name where the AKS cluster resides | `rg-attcc-opsportal-dev` |
| `AKS_CLUSTER_NAME` | AKS cluster name (also checked as `AKS_CLUSTER`) | `aks-attcc-opsportal-dev` |
| `KEYVAULT_NAME` | Azure Key Vault name used by CSI SecretStore for injecting secrets into pods | `kv-attcc-opsportal-dev` |

---

## Environment-Specific Secrets

### `dev` environment 🔒

| Secret Name | Purpose | Sample Value |
|---|---|---|
| `AZURE_CLIENT_ID` | SP client ID for dev | `11111111-1111-1111-1111-111111111111` |
| `AZURE_TENANT_ID` | Tenant for dev | `22222222-2222-2222-2222-222222222222` |
| `AZURE_SUBSCRIPTION_ID` | Subscription for dev | `33333333-3333-3333-3333-333333333333` |
| `AKS_RESOURCE_GROUP` | Dev AKS resource group | `rg-attcc-opsportal-dev` |
| `AKS_CLUSTER_NAME` | Dev AKS cluster | `aks-attcc-opsportal-dev` |
| `KEYVAULT_NAME` | Dev Key Vault | `kv-attcc-opsportal-dev` |
| `DEV_HOSTNAME` | Ingress hostname for dev | `opsportal-dev.test.att.com` |

### `prod` environment 🔒

| Secret Name | Purpose | Sample Value |
|---|---|---|
| `AZURE_CLIENT_ID` | SP client ID for prod | `44444444-4444-4444-4444-444444444444` |
| `AZURE_TENANT_ID` | Tenant for prod | `22222222-2222-2222-2222-222222222222` |
| `AZURE_SUBSCRIPTION_ID` | Subscription for prod | `55555555-5555-5555-5555-555555555555` |
| `AZURE_CLIENT_SECRET` | SP secret for kubelogin SPN mode | `xYz~ProdSecretValue.0123456789abcdef` |
| `AKS_RESOURCE_GROUP` | Prod AKS resource group | `rg-attcc-opsportal-prod` |
| `AKS_CLUSTER_NAME` | Prod AKS cluster | `aks-attcc-opsportal-prod` |
| `KEYVAULT_NAME` | Prod Key Vault | `kv-attcc-opsportal-prod` |
| `PROD_HOSTNAME` | Ingress hostname for prod | `opsportal.att.com` |

---

## Auto-Provided (No Configuration Needed)

| Variable | Source |
|---|---|
| `GITHUB_TOKEN` | Automatically injected by GitHub Actions |
| `GITHUB_SHA` | Automatically set to the commit SHA |
| `GITHUB_REF` | Automatically set to the triggering ref |

---

## Pipeline-Level Environment Variables (Hardcoded in Workflow)

These are **not** secrets — they are defined directly in the workflow `env:` block and may be modified by editing the YAML.

| Variable | Current Value | Purpose |
|---|---|---|
| `JFROG_REGISTRY` | `artifact.it.att.com` | Base JFrog Docker registry domain |
| `IMAGE_REGISTRY_PATH` | `artifact.it.att.com/apm0014313-dkr-attcc-stage/com.att.attcc` | Full image path prefix |
| `HELM_RELEASE` | `ops-portal` | Helm release name |
| `HELM_CHART_PATH` | `helm/ops-portal` | Path to Helm chart in repo |
| `DEV_NAMESPACE` | `opsportal` | Kubernetes namespace for dev |
| `PROD_NAMESPACE` | `opsportal` | Kubernetes namespace for prod |
| `BACKEND_ENV_SECRET_NAME` | `ops-portal-backend-env` | K8s secret name for backend env |
| `FRONTEND_ENV_SECRET_NAME` | `ops-portal-frontend-env` | K8s secret name for frontend env |

---

## Frontend Build-Time Variables (Non-Secret)

Used during the `test-frontend` job for CI builds only (placeholders):

| Variable | CI Value | Production Value (set via `env-config.js`) |
|---|---|---|
| `VITE_AZURE_CLIENT_ID` | `placeholder` | Real Azure AD client ID for MSAL |
| `VITE_AZURE_TENANT_ID` | `placeholder` | Real Azure AD tenant ID |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend API URL (e.g., `https://opsportal.att.com/api`) |

---

## Notes

1. **Workload Identity vs SPN**: Dev uses workload identity federation (`-l workloadidentity`), prod uses service principal (`-l spn` with `AZURE_CLIENT_SECRET`).
2. **Fallback patterns**: `AKS_CLUSTER_NAME` falls back to `AKS_CLUSTER` and also checks `vars.*` — configure either secrets or repository variables.
3. **Never commit** any of these values to source control. Use the GitHub UI or CLI (`gh secret set`) to configure them.
4. **Rotation**: Rotate `JFROG_PASSWORD`, `AUTH_NPM_TOKEN`, and `AZURE_CLIENT_SECRET` per your organization's secret rotation policy.
