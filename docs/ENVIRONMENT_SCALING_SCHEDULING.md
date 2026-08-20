# Environment Scaling & Scheduling Module

## Overview

The Environment Scaling & Scheduling module extends the AKS Operations Center with comprehensive environment lifecycle management capabilities. Administrators can start, stop, and schedule complete application environments while maintaining application dependency order.

**Navigation:** Sidebar → "Env Scheduler" (under AKS Operations module)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend                                 │
│  EnvironmentSchedulerPage                                       │
│  ├── EnvironmentScaleDialog (manual scale up/down)              │
│  ├── ScheduleManagement (CRUD for automated schedules)          │
│  ├── SequenceDesigner (drag-and-drop startup/shutdown order)    │
│  └── ExecutionHistory (searchable audit grid)                   │
└─────────────────────────┬───────────────────────────────────────┘
                          │ REST API
┌─────────────────────────▼───────────────────────────────────────┐
│                         Backend                                  │
│  /api/v1/environment/*                                          │
│  ├── environment.py (endpoint router)                           │
│  ├── environment_scaling_service.py (business logic)            │
│  ├── aks_operations_service.py (K8s API calls)                  │
│  └── scheduler_service.py (APScheduler cron runner)             │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                      PostgreSQL                                  │
│  ├── environment_schedules (scheduled jobs)                     │
│  ├── environment_sequences (startup/shutdown order)             │
│  ├── environment_execution_history (audit trail)                │
│  └── audit_logs (central audit)                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/environment/scale` | Scale up/down namespace or selected deployments | WRITE |
| `GET` | `/api/v1/environment/status` | Get deployment status for a namespace | READ |
| `GET` | `/api/v1/environment/schedule` | List all schedules | READ |
| `POST` | `/api/v1/environment/schedule` | Create a new schedule | WRITE |
| `PUT` | `/api/v1/environment/schedule/{id}` | Update a schedule | WRITE |
| `DELETE` | `/api/v1/environment/schedule/{id}` | Delete a schedule | WRITE |
| `GET` | `/api/v1/environment/sequence` | List all sequences | READ |
| `POST` | `/api/v1/environment/sequence` | Create a sequence | WRITE |
| `PUT` | `/api/v1/environment/sequence/{id}` | Update a sequence | WRITE |
| `DELETE` | `/api/v1/environment/sequence/{id}` | Delete a sequence | WRITE |
| `POST` | `/api/v1/environment/start-sequence` | Execute a startup sequence | WRITE |
| `POST` | `/api/v1/environment/stop-sequence` | Execute a shutdown sequence | WRITE |
| `GET` | `/api/v1/environment/history` | Get execution history | READ |

---

## Features

### 1. Manual Environment Scale

Scale all or selected deployments in a namespace with a single action.

**Request:**
```json
{
  "cluster_id": "/subscriptions/.../managedClusters/my-cluster",
  "namespace": "com-att-attcc-dev-merge",
  "operation": "scale_up",
  "scope": "namespace",
  "deployment_names": null,
  "replica_count": 1,
  "dry_run": false
}
```

**Response:**
```json
{
  "execution_id": 42,
  "status": "completed",
  "total_deployments": 187,
  "completed": 185,
  "failed": 0,
  "skipped": 2,
  "details": [
    {
      "deployment": "administration",
      "current_replicas": 0,
      "target_replicas": 1,
      "status": "completed"
    }
  ]
}
```

**Options:**
- **Scope:** Entire namespace or selected deployments
- **Operation:** Scale Up (custom replica count) or Scale Down (replicas=0)
- **Dry Run:** Preview changes without executing
- **Confirmation:** Required before scale-down operations

---

### 2. Scheduled Auto-Scaling

Create automated schedules that execute scaling operations at predefined times.

**Schedule Types:**
- One Time
- Daily
- Weekly
- Monthly
- Cron Expression (e.g., `0 8 * * 1-5` for weekdays at 8 AM)

**Example Schedules:**
```
Job: "Dev Morning Scale Up"
Namespace: com-att-attcc-dev-merge
Operation: Scale Up (replicas=1)
Schedule: Cron "0 8 * * 1-5" (Mon-Fri 8:00 AM)
Timezone: US/Eastern

Job: "Dev Evening Scale Down"
Namespace: com-att-attcc-dev-merge
Operation: Scale Down
Schedule: Cron "0 20 * * 1-5" (Mon-Fri 8:00 PM)
Timezone: US/Eastern
```

**Fields:**
- Job Name, Cluster, Namespace, Operation, Replica Count
- Schedule Type, Cron Expression, Timezone
- Start Date, End Date
- Enabled/Disabled toggle
- Retry Count (0-10)
- Failure Notification (email)

The scheduler runs every minute and executes due schedules automatically.

---

### 3. Sequence-Based Startup/Shutdown

Define dependency-aware startup or shutdown sequences for microservices that must start in order.

**Example Startup Sequence:**
```
Step 1: admin          → Replicas=1, Wait: Pods Ready, Timeout: 600s
    ↓
Step 2: compadmin      → Replicas=1, Wait: Pods Ready, Timeout: 600s
    ↓
Step 3: payeemanager   → Replicas=1, Wait: Deployment Available
    ↓
Step 4: paymentservice → Replicas=1, Wait: Health Endpoint
    ↓
Step 5: reportservice  → Replicas=1, Wait: Pods Ready
```

**Wait Conditions:**
| Condition | Description |
|-----------|-------------|
| `pods_ready` | Wait until `readyReplicas >= desiredReplicas` |
| `deployment_available` | Wait until `availableReplicas >= desiredReplicas` |
| `health_endpoint` | Wait until health URL returns HTTP 200 |
| `fixed_time` | Wait a fixed duration (uses timeout value) |
| `skip` | No wait — proceed immediately |

**Failure Handling:**
- **Abort on Failure:** Stop execution and optionally rollback
- **Continue on Failure:** Skip failed deployment and continue
- **Rollback:** Scales completed deployments back to 0

---

### 4. Execution History

All operations (manual, scheduled, sequence) are recorded with full audit detail.

**Recorded Fields:**
- Execution type (manual / scheduled / sequence)
- Cluster, Namespace, Operation
- Status (running / completed / failed / rolled_back)
- Per-deployment step details
- Initiated by (user ID and email)
- Start time, completion time, duration
- Error messages

---

## Database Schema

### `environment_schedules`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| job_name | VARCHAR(255) | Human-readable schedule name |
| cluster_id | VARCHAR(500) | Azure AKS resource ID |
| namespace | VARCHAR(255) | Kubernetes namespace |
| operation | VARCHAR(50) | `scale_up` or `scale_down` |
| replica_count | INTEGER | Target replica count |
| schedule_type | VARCHAR(50) | `one_time`, `daily`, `weekly`, `monthly`, `cron` |
| cron_expression | VARCHAR(255) | Cron syntax (if type=cron) |
| timezone | VARCHAR(100) | IANA timezone |
| start_date | DATETIME | Schedule activation date |
| end_date | DATETIME | Schedule expiration date |
| is_enabled | BOOLEAN | Active/inactive toggle |
| retry_count | INTEGER | Max retries on failure |
| failure_notification | VARCHAR(500) | Notification target |
| sequence_id | INTEGER FK | Optional linked sequence |
| created_by | VARCHAR(255) | Creator user ID |
| last_run_at | DATETIME | Last execution time |
| next_run_at | DATETIME | Next scheduled execution |
| last_run_status | VARCHAR(50) | Result of last execution |

### `environment_sequences`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| name | VARCHAR(255) UNIQUE | Sequence name |
| cluster_id | VARCHAR(500) | AKS cluster resource ID |
| namespace | VARCHAR(255) | Target namespace |
| sequence_type | VARCHAR(50) | `startup` or `shutdown` |
| steps | JSONB | Ordered array of step definitions |
| rollback_on_failure | BOOLEAN | Auto-rollback flag |
| created_by | VARCHAR(255) | Creator user ID |

**Step Schema (JSONB):**
```json
{
  "order": 1,
  "deployment_name": "admin",
  "replicas": 1,
  "wait_condition": "pods_ready",
  "timeout_seconds": 600,
  "health_endpoint": null,
  "retry_count": 3,
  "on_failure": "abort"
}
```

### `environment_execution_history`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| execution_type | VARCHAR(50) | `manual`, `scheduled`, `sequence` |
| cluster_id | VARCHAR(500) | Cluster resource ID |
| namespace | VARCHAR(255) | Target namespace |
| operation | VARCHAR(50) | Operation performed |
| status | VARCHAR(50) | `running`, `completed`, `failed`, `rolled_back` |
| total_deployments | INTEGER | Total targets |
| completed_count | INTEGER | Successfully scaled |
| failed_count | INTEGER | Failed deployments |
| skipped_count | INTEGER | Already at target (skipped) |
| step_details | JSONB | Per-deployment results |
| initiated_by | VARCHAR(255) | User who triggered |
| started_at | DATETIME | Execution start |
| completed_at | DATETIME | Execution end |
| duration_seconds | FLOAT | Total elapsed time |

---

## Frontend Components

| Component | Path | Purpose |
|-----------|------|---------|
| `EnvironmentSchedulerPage` | `src/pages/EnvironmentSchedulerPage.tsx` | Main page with dashboard, tabs |
| `EnvironmentScaleDialog` | `src/features/environment/EnvironmentScaleDialog.tsx` | Modal for manual scale |
| `ScheduleManagement` | `src/features/environment/ScheduleManagement.tsx` | CRUD grid for schedules |
| `SequenceDesigner` | `src/features/environment/SequenceDesigner.tsx` | Drag-and-drop builder |
| `ExecutionHistoryGrid` | `src/features/environment/ExecutionHistory.tsx` | History grid with details |
| `environmentApi.ts` | `src/services/environmentApi.ts` | React Query hooks + types |

---

## Access Control

- **Module:** `aks_operations`
- **Page:** `env_scheduler`
- **Read operations:** Require `READ` role or above
- **Write operations:** Require `WRITE` role or above
- **Admin:** Bypasses all access checks

The page is registered in `resource_registry.py` and automatically seeded on startup.

---

## Scheduler Integration

The environment schedule runner is registered in `scheduler_service.py` as a platform job:

```python
scheduler.add_job(
    run_environment_schedules_job,
    IntervalTrigger(minutes=1),
    id="environment_schedule_runner",
    name="Environment Schedule Runner",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

Every minute, the runner:
1. Queries all enabled schedules
2. Checks if `next_run_at <= now`
3. Validates start/end date boundaries
4. Executes the scaling operation
5. Computes and updates `next_run_at`
6. Records results in execution history

---

## Safety Controls

1. **Confirmation dialog** before scale-down operations
2. **Dry Run mode** to preview without executing
3. **RBAC enforcement** on all write endpoints
4. **Audit logging** for every operation
5. **Rollback support** for failed sequences
6. **Timeout enforcement** on wait conditions
7. **Graceful skip** for deployments already at target replicas

---

## File Index

```
backend/
├── app/
│   ├── api/v1/endpoints/environment.py     # API routes
│   ├── models/database.py                  # +3 models (EnvironmentSchedule, EnvironmentSequence, EnvironmentExecutionHistory)
│   ├── schemas/environment.py              # Pydantic request/response schemas
│   ├── services/environment_scaling_service.py  # Business logic
│   ├── services/scheduler_service.py       # +run_environment_schedules_job
│   └── core/resource_registry.py           # +env_scheduler page resource

frontend/
├── src/
│   ├── pages/EnvironmentSchedulerPage.tsx  # Main page
│   ├── services/environmentApi.ts          # API hooks + types
│   ├── features/environment/
│   │   ├── EnvironmentScaleDialog.tsx      # Manual scale modal
│   │   ├── ScheduleManagement.tsx          # Schedule CRUD
│   │   ├── SequenceDesigner.tsx            # Sequence builder
│   │   └── ExecutionHistory.tsx            # History grid
│   └── App.tsx                             # +route /env-scheduler + nav item
```
