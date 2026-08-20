# Azure Ops Intelligence & Optimization Portal — Architecture Blueprint

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AKS CLUSTER (attcc-ops-portal)                  │
│                                                                         │
│  ┌──────────────┐   ┌──────────────────────────┐   ┌────────────────┐  │
│  │   NGINX      │   │   Frontend (React SPA)    │   │  Backend       │  │
│  │   Ingress    │──▶│   - Leadership Dashboard  │   │  (FastAPI)     │  │
│  │   Controller │   │   - Ops Dashboard         │   │                │  │
│  │              │   │   - Admin Dashboard        │   │  /api/v1/...   │  │
│  │   TLS via    │   │   - Reports               │──▶│                │  │
│  │   cert-mgr   │   └──────────────────────────┘   │  Microservices │  │
│  └──────┬───────┘                                    │  Architecture  │  │
│         │                                            └───────┬────────┘  │
│         │                                                    │           │
│  ┌──────┴──────────────────────────────────────────────────┐ │           │
│  │              Workload Identity Federation                │ │           │
│  │         (Managed Identity → Azure AD Token)              │ │           │
│  └──────────────────────────────────────────────────────────┘ │           │
│                                                    ┌─────────┴────────┐ │
│                                                    │  Redis Cache     │ │
│                                                    │  (session/cache) │ │
│                                                    └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
         │                    │                         │
         ▼                    ▼                         ▼
┌─────────────────┐  ┌───────────────────┐  ┌──────────────────────┐
│  Azure AD       │  │ Azure Cost Mgmt   │  │ Azure Key Vault      │
│  (Entra ID)     │  │ REST API          │  │ (secrets, certs)     │
│  - Auth/RBAC    │  │ - Usage/Query     │  │ - Workload Identity  │
│  - App Reg      │  │ - Budgets         │  │ - RBAC secrets       │
│  - Roles        │  │ - Recommendations │  │                      │
└─────────────────┘  └───────────────────┘  └──────────────────────┘
         │                    │
         │                    ▼
         │           ┌───────────────────┐
         │           │ Azure Monitor     │
         │           │ - Resource Graph  │
         │           │ - Advisor         │
         │           │ - Metrics         │
         │           └───────────────────┘
         │
         ▼
┌─────────────────┐
│  SMTP Relay     │
│  mta01.az.3pc   │
│  .att.com:25    │
└─────────────────┘
```

## 2. Component Breakdown

### 2.1 Frontend — React SPA
| Component          | Technology          | Purpose                                    |
|--------------------|---------------------|--------------------------------------------|
| UI Framework       | React 18 + TypeScript | Core SPA                                 |
| Charts             | Recharts / Chart.js | Bar, Pie, Trend visualizations            |
| State Management   | React Query + Zustand | API caching & local state               |
| Auth               | MSAL.js (@azure/msal-react) | Azure AD SSO                     |
| PDF Generation     | react-pdf / jsPDF   | Client-side report rendering              |
| Styling            | Tailwind CSS        | Enterprise-grade responsive UI            |

### 2.2 Backend — FastAPI Microservices
| Service                  | Path Prefix           | Responsibility                           |
|--------------------------|-----------------------|------------------------------------------|
| Cost Service             | /api/v1/costs         | Cost data ingestion & aggregation        |
| Optimization Service     | /api/v1/optimize      | FinOps recommendations & wastage         |
| Auth Service             | /api/v1/auth          | Token validation, RBAC enforcement       |
| Notification Service     | /api/v1/notifications | SMTP alerts, budget notifications        |
| Report Service           | /api/v1/reports       | PDF generation, scheduling               |
| Admin Service            | /api/v1/admin         | Subscription & user management           |
| Plugin Service           | /api/v1/plugins       | Extensible module loading                |

### 2.3 Data Flow
1. **Ingestion**: Backend polls Azure Cost Management API (Usage/Query) daily
2. **Caching**: Results cached in Redis (TTL: 1hr for dashboards, 24hr for reports)
3. **Aggregation**: Backend aggregates by subscription, resource group, type, category
4. **Optimization**: Advisor API + custom heuristics produce recommendations
5. **Presentation**: React frontend renders dashboards via REST API

## 3. Security Architecture

- **Authentication**: Azure AD (Entra ID) via MSAL — OIDC/OAuth2 code flow
- **Authorization**: Claims-based RBAC (Admin / Write / Read) via FastAPI middleware
- **Secrets**: Azure Key Vault + Workload Identity — zero secrets in config
- **Network**: AKS Network Policy, private ingress options, TLS termination
- **Audit**: All API calls logged with user identity, action, timestamp
- **Least Privilege**: Managed Identity scoped to `Cost Management Reader` + `Reader`

## 4. AKS Cluster Architecture

| Node Pool     | VM SKU          | Min | Max | Purpose                    |
|---------------|-----------------|-----|-----|----------------------------|
| system        | Standard_D2s_v5 | 2   | 3   | System pods, ingress       |
| app           | Standard_D4s_v5 | 2   | 5   | Application workloads      |

- **Ingress**: NGINX Ingress Controller with TLS (cert-manager + Let's Encrypt)
- **Scaling**: HPA on CPU/memory; Cluster Autoscaler enabled
- **Networking**: Azure CNI with Network Policies

## 5. Extensibility Strategy

The portal uses a **plugin-based architecture**:

```
backend/
  app/
    plugins/
      __init__.py          # Plugin registry & loader
      base.py              # Abstract plugin interface
      aks_insights/        # AKS operational module
      keyvault_ops/        # Key Vault management module
      cost_optimizer/      # FinOps optimization (built-in)
```

Each plugin implements `PluginBase` and registers:
- API routes (FastAPI Router)
- Permissions required
- Dashboard widgets (metadata for frontend)

New modules are added by:
1. Creating a new directory under `plugins/`
2. Implementing the `PluginBase` interface
3. Updating `plugin_registry.yaml`
4. Frontend discovers available plugins via `/api/v1/plugins/registry`

---

## 6. Module 2: AKS Operations & Control Center

### 6.1 Overview
A comprehensive AKS management module providing multi-subscription cluster inventory, deployment scaling/restart operations, pod observability, and CronJob management.

### 6.2 Service Architecture

| Service File                    | Purpose                                              |
|---------------------------------|------------------------------------------------------|
| `aks_operations_service.py`     | Core AKS operations (clusters, deployments, pods)    |

### 6.3 API Endpoints

| Endpoint                              | Method | Description                                    |
|---------------------------------------|--------|------------------------------------------------|
| `/api/v1/aks/clusters`                | GET    | List all clusters across subscriptions         |
| `/api/v1/aks/clusters/{cluster_id}`   | GET    | Get detailed cluster information               |
| `/api/v1/aks/clusters/snapshot`       | POST   | Snapshot all cluster configurations            |
| `/api/v1/aks/deployments`             | GET    | List deployments with filters                  |
| `/api/v1/aks/deployments/scale`       | POST   | Scale deployment replicas                      |
| `/api/v1/aks/deployments/restart`     | POST   | Restart deployment (rollout restart)           |
| `/api/v1/aks/pods/metrics`            | GET    | Get pod CPU/memory metrics                     |
| `/api/v1/aks/pods/utilization/history`| GET    | Historical pod utilization data                |
| `/api/v1/aks/pods/underutilized`      | GET    | Identify underutilized workloads               |
| `/api/v1/aks/cronjobs`                | GET    | List all CronJobs                              |
| `/api/v1/aks/cronjobs`                | POST   | Create new CronJob                             |
| `/api/v1/aks/cronjobs/suspend`        | POST   | Suspend/resume CronJob                         |
| `/api/v1/aks/scale-history`           | GET    | Deployment scale audit history                 |

### 6.4 Database Models

| Model                    | Purpose                                              |
|--------------------------|------------------------------------------------------|
| `AKSClusterSnapshot`     | Point-in-time cluster configuration snapshots        |
| `AKSNodePoolSnapshot`    | Node pool configuration snapshots                    |
| `DeploymentScaleHistory` | Audit trail for deployment scale operations          |
| `PodUtilizationHistory`  | Historical pod CPU/memory utilization metrics        |
| `CronJobAuditHistory`    | Audit trail for CronJob suspend/resume operations    |

### 6.5 Frontend Components

| Component              | Location                                    | Features                           |
|------------------------|---------------------------------------------|------------------------------------|
| `AKSOperationsPage`    | `frontend/src/components/AKSOperationsPage.tsx` | 5 tabs: Clusters, Deployments, Pod Metrics, CronJobs, Scale History |

### 6.6 Key Features
- **Cluster Inventory**: Multi-subscription discovery with node pool details
- **Deployment Operations**: Scale replicas, rollout restart with confirmation dialogs
- **Pod Observability**: CPU/memory metrics with trend charts, underutilization detection
- **CronJob Management**: Suspend/resume, create new CronJobs, audit history
- **Scale History**: Full audit trail of scale operations with user attribution

---

## 7. Module 3: Compliance & Drift Detection

### 7.1 Overview
Automated compliance monitoring for Synapse pipelines and AKS workloads. Detects configuration drift, calculates compliance scores, and provides remediation tracking.

### 7.2 Service Architecture

| Service File                    | Purpose                                              |
|---------------------------------|------------------------------------------------------|
| `compliance_service.py`         | Checksum collection, drift detection, scoring        |

### 7.3 API Endpoints

| Endpoint                                    | Method | Description                                    |
|---------------------------------------------|--------|------------------------------------------------|
| `/api/v1/compliance/synapse/collect-checksums` | POST | Collect Synapse pipeline checksums            |
| `/api/v1/compliance/synapse/drift`          | GET    | Get Synapse pipeline drift records             |
| `/api/v1/compliance/synapse/drift/summary`  | GET    | Aggregated drift summary                       |
| `/api/v1/compliance/synapse/drift/{id}/acknowledge` | POST | Acknowledge drift (with comment)        |
| `/api/v1/compliance/aks/collect-checksums`  | POST   | Collect AKS pod configuration checksums        |
| `/api/v1/compliance/aks/drift`              | GET    | Get AKS pod drift records                      |
| `/api/v1/compliance/aks/drift/timeline`     | GET    | Time-series drift data                         |
| `/api/v1/compliance/scores/calculate`       | POST   | Calculate compliance score                     |
| `/api/v1/compliance/dashboard`              | GET    | Compliance dashboard data with scores/trends   |
| `/api/v1/compliance/drift-categories`       | GET    | Drift breakdown by category                    |

### 7.4 Database Models

| Model                    | Purpose                                              |
|--------------------------|------------------------------------------------------|
| `SynapsePipelineChecksum`| Baseline Synapse pipeline configuration hashes       |
| `SynapsePipelineDrift`   | Detected Synapse drift records with remediation      |
| `AKSPodChecksum`         | Baseline AKS pod configuration hashes                |
| `AKSPodDrift`            | Detected AKS pod drift records                       |
| `ComplianceScore`        | Point-in-time compliance scores with breakdown       |

### 7.5 Frontend Components

| Component              | Location                                    | Features                           |
|------------------------|---------------------------------------------|------------------------------------|
| `CompliancePage`       | `frontend/src/components/CompliancePage.tsx` | 4 tabs: Dashboard, Synapse Drift, AKS Pod Drift, Timeline |

### 7.6 Compliance Scoring

Scores are calculated using a weighted formula:
- **Total Drift Weight** = Σ(drift_score × severity_weight)
- **Score** = 100 - min(total_drift_weight, 100)

| Grade | Score Range | Indicator |
|-------|-------------|-----------|
| A     | 90-100      | Green     |
| B     | 80-89       | Light Green |
| C     | 70-79       | Yellow    |
| D     | 60-69       | Orange    |
| F     | < 60        | Red       |

### 7.7 Key Features
- **Synapse Drift Detection**: Pipeline checksum tracking, drift alerts, acknowledgement workflow
- **AKS Pod Drift Detection**: Container config monitoring, image version tracking
- **Compliance Dashboard**: Real-time score, trend charts, drift category breakdown
- **Timeline View**: Historical drift patterns for trend analysis
- **Remediation Tracking**: Acknowledged vs unacknowledged drift management

---

## 8. Database Schema

### 8.1 Core Model: AuditLog
```python
class AuditLog(Base):
    id: UUID (PK)
    user_id: String
    user_email: String
    action: String
    resource_type: String
    resource_id: String
    details: JSON
    ip_address: String
    timestamp: DateTime
```

### 8.2 ER Diagram Summary
```
┌─────────────────────┐     ┌─────────────────────┐
│  AKSClusterSnapshot │◄───│ AKSNodePoolSnapshot │
└─────────────────────┘     └─────────────────────┘
          │
          ▼
┌─────────────────────┐     ┌─────────────────────┐
│DeploymentScaleHistory│    │ PodUtilizationHistory│
└─────────────────────┘     └─────────────────────┘
          │
          ▼
┌─────────────────────┐
│ CronJobAuditHistory │
└─────────────────────┘

┌──────────────────────┐    ┌─────────────────────┐
│SynapsePipelineChecksum│◄──│ SynapsePipelineDrift │
└──────────────────────┘    └─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│   AKSPodChecksum    │◄───│    AKSPodDrift      │
└─────────────────────┘     └─────────────────────┘
          │
          ▼
┌─────────────────────┐
│   ComplianceScore   │
└─────────────────────┘
```

---

## 9. Technology Stack Summary

### 9.1 Backend Dependencies
| Package                      | Version   | Purpose                            |
|------------------------------|-----------|-------------------------------------|
| fastapi                      | ≥0.100.0  | REST API framework                  |
| azure-identity               | ≥1.15.0   | Azure AD authentication             |
| azure-mgmt-containerservice  | ≥26.0.0   | AKS management operations           |
| azure-mgmt-monitor           | ≥6.0.0    | Azure Monitor metrics               |
| azure-mgmt-synapse           | ≥2.0.0    | Synapse workspace management        |
| kubernetes                   | ≥29.0.0   | Kubernetes API client               |
| sqlalchemy[asyncio]          | ≥2.0.0    | Async ORM with PostgreSQL           |
| asyncpg                      | ≥0.29.0   | Async PostgreSQL driver             |
| alembic                      | ≥1.13.0   | Database migrations                 |

### 9.2 Frontend Dependencies
| Package                      | Purpose                            |
|------------------------------|------------------------------------|
| react                        | Core UI framework (v18)            |
| @tanstack/react-query        | Server state management            |
| recharts                     | Data visualization                 |
| tailwindcss                  | Utility-first CSS                  |
| @azure/msal-react            | Azure AD authentication            |

---

## 10. Deployment Architecture

### 10.1 Helm Values (Key)
```yaml
backend:
  replicas: 2
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 2Gi
  env:
    AZURE_CLIENT_ID: ${MANAGED_IDENTITY_CLIENT_ID}
    DATABASE_URL: postgresql+asyncpg://...

frontend:
  replicas: 2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
```

### 10.2 Required Azure RBAC Roles
| Role                          | Scope                    | Purpose                          |
|-------------------------------|--------------------------|----------------------------------|
| Cost Management Reader        | Subscription(s)          | Cost data access                 |
| Reader                        | Subscription(s)          | Resource enumeration             |
| Azure Kubernetes Service RBAC Reader | AKS Clusters      | Cluster operations               |
| Synapse Contributor           | Synapse Workspaces       | Pipeline metadata access         |

---

## 11. Future Enhancements

1. **Multi-AKS Federation**: Support for multiple AKS clusters in single view
2. **GitOps Integration**: ArgoCD/Flux drift detection and remediation
3. **Cost Anomaly Detection**: ML-based cost spike alerting
4. **Automated Remediation**: Self-healing for common drift scenarios
5. **Report Export**: Scheduled compliance report generation (PDF/Excel)
