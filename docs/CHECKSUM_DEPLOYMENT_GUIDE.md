# Checksum Automation System - Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying the checksum automation system for both **Synapse** and **AKS** environments. The system provides scheduled, automated checksum verification with notifications and compliance tracking.

## Prerequisites

- Azure subscription with appropriate permissions
- AKS cluster (if deploying AKS checksums)
- Synapse workspace (if deploying Synapse checksums)
- PostgreSQL database for maintaining schedule configurations
- Docker registry access for container images
- Azure Key Vault configured with necessary secrets

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│           Checksum Automation System                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────┐      ┌──────────────────┐        │
│  │  Synapse Module  │      │   AKS Module     │        │
│  ├──────────────────┤      ├──────────────────┤        │
│  │ • Workspace      │      │ • Cluster        │        │
│  │ • Containers     │      │ • Namespaces     │        │
│  │ • Datasets       │      │ • Services       │        │
│  │ • Databases      │      │ • ConfigMaps     │        │
│  └────────┬─────────┘      └────────┬─────────┘        │
│           │                         │                  │
│           └────────────┬────────────┘                  │
│                        │                              │
│           ┌────────────▼────────────┐                │
│           │  Compliance Service     │                │
│           ├────────────────────────┤                │
│           │ • Scheduling           │                │
│           │ • Verification         │                │
│           │ • Reporting            │                │
│           │ • Notifications        │                │
│           └────────────┬────────────┘                │
│                        │                              │
│           ┌────────────▼────────────┐                │
│           │   PostgreSQL Database   │                │
│           ├────────────────────────┤                │
│           │ • Schedules            │                │
│           │ • Results              │                │
│           │ • Audit Logs           │                │
│           └────────────────────────┘                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## Deployment Steps

### Phase 1: Database Setup

#### 1.1 Create PostgreSQL Tables

```bash
# Connect to PostgreSQL
psql -h <postgres-host> -U <admin-user> -d <database>

# Run migrations
psql -h <postgres-host> -U <admin-user> -d <database> \
  -f migrations/001_create_checksum_schedules.sql
```

**Migration SQL** (`migrations/001_create_checksum_schedules.sql`):

```sql
-- Create checksum_schedule_configs table
CREATE TABLE IF NOT EXISTS checksum_schedule_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    module_type VARCHAR(50) NOT NULL CHECK (module_type IN ('synapse', 'aks')),
    system VARCHAR(100),
    environment VARCHAR(100),
    workspace_name VARCHAR(255),
    cluster_id VARCHAR(255),
    cluster_name VARCHAR(255),
    namespaces TEXT[] DEFAULT '{}',
    schedule_type VARCHAR(50) NOT NULL CHECK (schedule_type IN ('interval', 'cron')),
    interval_hours INTEGER CHECK (interval_hours > 0),
    cron_expression VARCHAR(255),
    timezone VARCHAR(100) DEFAULT 'UTC',
    notification_emails TEXT[] DEFAULT '{}',
    is_enabled BOOLEAN DEFAULT true,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    updated_at TIMESTAMP,
    updated_by VARCHAR(255),
    CONSTRAINT valid_schedule CHECK (
        (schedule_type = 'interval' AND interval_hours IS NOT NULL) OR
        (schedule_type = 'cron' AND cron_expression IS NOT NULL)
    )
);

-- Create checksum_results table
CREATE TABLE IF NOT EXISTS checksum_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID NOT NULL REFERENCES checksum_schedule_configs(id) ON DELETE CASCADE,
    module_type VARCHAR(50) NOT NULL,
    system VARCHAR(100),
    environment VARCHAR(100),
    status VARCHAR(50) NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    checksum_value VARCHAR(256),
    previous_checksum VARCHAR(256),
    matches BOOLEAN,
    error_message TEXT,
    duration_seconds FLOAT,
    verified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_by VARCHAR(255)
);

-- Create indexes for faster queries
CREATE INDEX idx_checksum_schedule_configs_module_type 
    ON checksum_schedule_configs(module_type);
CREATE INDEX idx_checksum_schedule_configs_is_enabled 
    ON checksum_schedule_configs(is_enabled);
CREATE INDEX idx_checksum_results_schedule_id 
    ON checksum_results(schedule_id);
CREATE INDEX idx_checksum_results_status 
    ON checksum_results(status);
CREATE INDEX idx_checksum_results_created_at 
    ON checksum_results(created_at DESC);
```

#### 1.2 Verify Database Setup

```bash
# Connect to database and verify tables
psql -h <postgres-host> -U <admin-user> -d <database> -c \
  "SELECT tablename FROM pg_tables WHERE schemaname='public';"

# Output should include:
# checksum_schedule_configs
# checksum_results
```

### Phase 2: Backend Deployment

#### 2.1 Deploy FastAPI Service

```bash
# Navigate to backend directory
cd azure-ops-portal/backend

# Build Docker image
docker build -t checksum-api:1.0.0 \
  -t <registry>/checksum-api:1.0.0 .

# Push to registry
docker push <registry>/checksum-api:1.0.0
```

#### 2.2 Configure Environment Variables

Create `.env` file:

```bash
# Database
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>

# Azure
AZURE_SUBSCRIPTION_ID=<subscription-id>
AZURE_TENANT_ID=<tenant-id>

# Synapse (if applicable)
SYNAPSE_WORKSPACE_NAME=<workspace-name>
SYNAPSE_ENDPOINT=https://<workspace-name>.dev.azuresynapse.net

# AKS (if applicable)
AKS_CLUSTER_NAME=<cluster-name>
AKS_RESOURCE_GROUP=<resource-group>

# Notifications
SMTP_SERVER=<smtp-server>
SMTP_PORT=587
SMTP_USERNAME=<smtp-username>
SMTP_PASSWORD=<smtp-password>
FROM_EMAIL=alerts@company.com

# Security
SECRET_KEY=<generate-secure-random-string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Logging
LOG_LEVEL=INFO
```

#### 2.3 Deploy to AKS

```bash
# Navigate to K8s manifests directory
cd kubernetes/

# Apply ConfigMap with non-sensitive environment variables
kubectl apply -f configmap.yaml

# Apply Secrets from Key Vault (or create manually)
kubectl apply -f secrets.yaml

# Deploy the application
kubectl apply -f deployment.yaml

# Verify deployment
kubectl rollout status deployment/checksum-api-deployment
kubectl get pods -l app=checksum-api
```

**Sample Deployment YAML** (`kubernetes/deployment.yaml`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checksum-api-deployment
  namespace: default
  labels:
    app: checksum-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: checksum-api
  template:
    metadata:
      labels:
        app: checksum-api
    spec:
      serviceAccountName: checksum-api-sa
      containers:
      - name: checksum-api
        image: <registry>/checksum-api:1.0.0
        imagePullPolicy: Always
        ports:
        - containerPort: 8000
          name: http
        envFrom:
        - configMapRef:
            name: checksum-api-config
        - secretRef:
            name: checksum-api-secrets
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        livenessProbe:
          httpGet:
            path: /api/health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 20
        readinessProbe:
          httpGet:
            path: /api/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: checksum-api-service
  labels:
    app: checksum-api
spec:
  type: ClusterIP
  selector:
    app: checksum-api
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: checksum-api-sa
  namespace: default
```

### Phase 3: Schedule Job Deployment

#### 3.1 Deploy Scheduler Job

```bash
# Navigate to scheduler directory
cd kubernetes/jobs/

# Deploy the scheduler job
kubectl apply -f scheduler-job.yaml

# Verify job
kubectl get jobs -l app=checksum-scheduler
kubectl logs -l app=checksum-scheduler
```

**Scheduler Job YAML** (`kubernetes/jobs/scheduler-job.yaml`):

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: checksum-scheduler
  namespace: default
spec:
  schedule: "*/5 * * * *"  # Run every 5 minutes
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
            app: checksum-scheduler
        spec:
          serviceAccountName: checksum-scheduler-sa
          containers:
          - name: scheduler
            image: <registry>/checksum-scheduler:1.0.0
            imagePullPolicy: Always
            envFrom:
            - secretRef:
                name: checksum-api-secrets
          restartPolicy: OnFailure
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: checksum-scheduler-sa
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: checksum-scheduler-role
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: checksum-scheduler-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: checksum-scheduler-role
subjects:
- kind: ServiceAccount
  name: checksum-scheduler-sa
  namespace: default
```

### Phase 4: Frontend Deployment

#### 4.1 Build Frontend

```bash
cd azure-ops-portal/frontend

npm install
npm run build

# Verify build
ls -la dist/
```

#### 4.2 Deploy frontend to Azure Static Web App or Blob Storage

**Option A: Azure Static Web App**

```bash
# Deploy using Azure CLI
az staticwebapp create \
  --name checksum-portal \
  --resource-group <rg-name> \
  --source <github-repo-url> \
  --location <location> \
  --sku Standard
```

**Option B: Blob Storage**

```bash
# Upload build artifacts
az storage blob upload-batch \
  --account-name <storage-account> \
  --source ./dist \
  --destination '$web'

# Configure CDN (optional)
az cdn endpoint create \
  --resource-group <rg-name> \
  --profile-name <cdn-profile> \
  --name <endpoint-name> \
  --origin <storage-account>
```

### Phase 5: Verify Deployment

#### 5.1 Health Checks

```bash
# Check backend API
curl http://checksum-api-service:80/api/health

# Expected response:
# {"status": "healthy", "timestamp": "2024-01-15T12:00:00Z"}

# Check database connectivity
kubectl exec -it deployment/checksum-api-deployment \
  -- python -c "from app.core.database import engine; print('DB OK')"
```

#### 5.2 Create First Schedule

```bash
# Use curl to create a test schedule
curl -X POST http://checksum-api-service/api/checksum-schedules \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "Test ATTCC Synapse",
    "module_type": "synapse",
    "system": "ATTCC",
    "environment": "prod",
    "workspace_name": "attcc-workspace",
    "schedule_type": "interval",
    "interval_hours": 24,
    "timezone": "America/Chicago",
    "notification_emails": ["admin@company.com"],
    "is_enabled": true
  }'
```

#### 5.3 Monitor Execution

```bash
# Watch logs
kubectl logs -f deployment/checksum-api-deployment

# Check schedule status
curl http://checksum-api-service/api/checksum-schedules \
  -H "Authorization: Bearer <token>"
```

## Post-Deployment Configuration

### 1. Set Up Notifications

Configure email notifications in Azure Key Vault:

```bash
az keyvault secret set \
  --vault-name <keyvault-name> \
  --name smtp-password \
  --value '<password>'

az keyvault secret set \
  --vault-name <keyvault-name> \
  --name notification-email-list \
  --value 'admin@company.com,operations@company.com'
```

### 2. Configure Monitoring

```bash
# Create Application Insights
az monitor app-insights component create \
  --resource-group <rg-name> \
  --app checksum-monitoring

# Create Log Analytics Workspace
az monitor log-analytics workspace create \
  --resource-group <rg-name> \
  --workspace-name checksum-logs
```

### 3. Set Up Alerts

```bash
# Alert for failed checksum verifications
az monitor metrics alert create \
  --name checksum-failures \
  --resource-group <rg-name> \
  --scopes /subscriptions/<sub-id>/resourceGroups/<rg-name> \
  --condition "avg checksum_failures > 0" \
  --window-size 5m \
  --evaluation-frequency 1m \
  --action <action-group-id>
```

## Troubleshooting

### Issue: Database Connection Failed

```bash
# Verify connection string
kubectl exec -it deployment/checksum-api-deployment \
  -- env | grep DATABASE_URL

# Test PostgreSQL connectivity
kubectl run -it --rm postgres-test \
  --image=postgres:15 \
  --restart=Never \
  -- psql -h <postgres-host> -U <user> -d <database> -c "SELECT 1"
```

### Issue: Schedules Not Executing

```bash
# Check scheduler logs
kubectl logs -l app=checksum-scheduler
kubectl logs -f cronjob.batch/checksum-scheduler

# Verify schedule configuration
kubectl exec -it deployment/checksum-api-deployment \
  -- python -c \
  "from app.models import ChecksumScheduleConfig; \
   from sqlalchemy import create_engine; \
   engine = create_engine(os.getenv('DATABASE_URL')); \
   Session = sessionmaker(bind=engine); \
   s = Session(); \
   print(s.query(ChecksumScheduleConfig).filter_by(is_enabled=True).all())"
```

### Issue: Authentication Failures

```bash
# Verify token generation
curl -X POST http://checksum-api-service/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "test"}'

# Check Azure AD integration
az ad token-credential \
  --service-principal <client-id> \
  --domain <tenant-id>
```

## Rollback Procedures

### Rolling Back Container Image

```bash
# Get previous image version
kubectl rollout history deployment/checksum-api-deployment

# Rollback to previous version
kubectl rollout undo deployment/checksum-api-deployment

# Verify rollback
kubectl rollout status deployment/checksum-api-deployment
```

### Rolling Back Database

```bash
# If migration failed, restore from backup
pg_restore -d <database> -U <user> backup.dump

# Verify restoration
psql -h <host> -U <user> -d <database> -c "SELECT COUNT(*) FROM checksum_schedule_configs;"
```

## Performance Tuning

### Database Optimization

```sql
-- Add partitioning for large result tables
ALTER TABLE checksum_results
PARTITION BY RANGE (created_at);

-- Maintain statistics
ANALYZE checksum_schedule_configs;
ANALYZE checksum_results;

-- Vacuum regularly
VACUUM ANALYZE;
```

### API Optimization

```yml
# Configure caching in deployment
apiVersion: v1
kind: ConfigMap
metadata:
  name: checksum-api-config
data:
  CACHE_ENABLED: "true"
  CACHE_TTL_SECONDS: "3600"
  LOG_LEVEL: "INFO"
```

## Security Hardening

### Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: checksum-api-policy
spec:
  podSelector:
    matchLabels:
      app: checksum-api
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 5432  # PostgreSQL
```

### RBAC Configuration

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: checksum-api-role
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: checksum-api-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: checksum-api-role
subjects:
- kind: ServiceAccount
  name: checksum-api-sa
  namespace: default
```

## References

- [Azure Synapse Documentation](https://learn.microsoft.com/en-us/azure/synapse-analytics/)
- [Azure Kubernetes Service Documentation](https://learn.microsoft.com/en-us/azure/aks/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

## Support

For issues or questions:
1. Check logs: `kubectl logs -f deployment/checksum-api-deployment`
2. Review database: `SELECT * FROM checksum_results ORDER BY created_at DESC LIMIT 10;`
3. Open an issue in the repository with logs and configuration details
