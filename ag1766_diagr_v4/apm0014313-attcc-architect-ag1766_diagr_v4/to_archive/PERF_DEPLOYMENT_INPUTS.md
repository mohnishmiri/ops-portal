# PERF Deployment Inputs

The CI and local Docker slice is ready for review. A PERF deployment workflow should not be added until the following values are confirmed by the platform owner.

## Required decisions

- Target platform: ECS, EKS, App Runner, VM, or another runtime.
- AWS account, region, environment name, and service or namespace.
- GitHub Actions runner type, network access, and IAM/OIDC role.
- Container registry and repository URI, image naming, and tag policy.
- Registry authentication mechanism and GitHub secret or variable names.
- Public hostname, ingress or load balancer, service port, and health-check path.
- Runtime configuration names and secret-manager mappings, including `DATABASE_URL` and `CSRF_SECRET`.
- Database migration owner, command, execution order, locking behavior, and rollback policy.
- PERF database endpoint and connectivity requirements.
- Replica count, CPU/memory limits, deployment strategy, and rollback trigger.
- Catalog initialization or publication requirements for the target database.
- Evidence and application-data storage requirements, including persistence and backup policy.

## Current application contract

- Container listens on port `8000`.
- Liveness endpoint: `/health/live`.
- Readiness endpoint: `/health/ready`.
- Default database strategy is python-oracledb thin mode.
- Oracle thick mode is opt-in through externally supplied client libraries.
- The container runs as a non-root `app` user.
- CI currently builds the image but does not publish or deploy it.

Once the platform owner supplies these values, add a separately reviewed PERF workflow and deployment manifests. Do not place credentials or client evidence in this repository.
