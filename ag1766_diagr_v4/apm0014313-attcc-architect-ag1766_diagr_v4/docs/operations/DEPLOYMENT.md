# Shared Test Deployment

The `ma4941_aifp_ui_cicd` branch deploys the application to AKS at:

`https://aws-outpost.test.att.com`

The deployment builds an immutable image tagged with the Git commit SHA, pushes it to Azure Container Registry, applies database migrations in an init container, and performs an atomic Helm rollout.

## GitHub Environment

Create a protected GitHub environment named `shared-test` with these variables:

| Variable | Purpose |
|---|---|
| `AZURE_TENANT_ID` | Microsoft Entra tenant used by workload identity |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing ACR and AKS |
| `AZURE_RESOURCE_GROUP` | AKS resource group |
| `AKS_CLUSTER_NAME` | Target AKS cluster |
| `ACR_NAME` | Azure Container Registry resource name |
| `K8S_NAMESPACE` | Target namespace, for example `migration-intake-tst` |

Add these environment secrets:

| Secret | Purpose |
|---|---|
| `AZURE_CLIENT_ID` | Federated workload identity client ID |
| `AWS_OUTPOST_DATABASE_URL` | Production-form SQLAlchemy Oracle URL |
| `AWS_OUTPOST_CSRF_SECRET` | Random application secret of at least 32 characters |

The federated identity needs permission to push to ACR, read AKS credentials, and deploy resources in the target namespace. The AKS kubelet identity also needs `AcrPull` on the registry.

## DNS And TLS

Before the first deployment:

1. Create the DNS record `aws-outpost.test.att.com` pointing to the NGINX ingress load balancer address.
2. Provision a certificate for `aws-outpost.test.att.com` as the Kubernetes TLS secret `aws-outpost-test-tls` in the target namespace.
3. Confirm the cluster has the NGINX ingress controller and the `azurefile-csi` storage class.
4. Confirm AKS network policy permits Oracle connectivity and DNS/HTTPS egress required by the application.

The workflow deliberately verifies the TLS secret and stops before deployment when it is absent. DNS and certificate issuance remain infrastructure operations because repository automation does not own the enterprise DNS zone or certificate authority.

## Local Validation

```bash
helm lint helm --values helm/envs/test.yaml \
  --set-string image.repository=example.azurecr.io/migration-intake \
  --set-string image.tag=test

helm template migration-intake helm --values helm/envs/test.yaml \
  --set-string image.repository=example.azurecr.io/migration-intake \
  --set-string image.tag=test

docker build --tag migration-intake:test .
```

Do not commit runtime credentials or generated Kubernetes Secret manifests.