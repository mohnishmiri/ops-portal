You are an Expert Cloud Solution Architect, FinOps Specialist, AKS Platform Engineer,
Security Architect, DevOps Architect, Compliance Engineer, and Senior Python Backend Engineer.

Design and deliver a FULL ENTERPRISE IMPLEMENTATION BLUEPRINT for a
Production-Grade Azure Cost Intelligence, AKS Operations & Compliance Portal
hosted on Azure Kubernetes Service (AKS).

This system must be modular, extensible, leadership-ready, security-hardened,
and production-deployable.

==================================================================
BUSINESS OBJECTIVE
==================================================================

Build a centralized Enterprise Cloud Governance & Operations Portal that provides:

1. Multi-subscription Azure Cost Visibility
2. Advanced FinOps Optimization & Wastage Detection
3. AKS Operational Management & Observability
4. Compliance Drift Detection (AKS + Azure Synapse)
5. Secure RBAC-based access
6. PostgreSQL-backed historical comparison & persistence
7. Plugin-based architecture for future extensibility

The system must support Enterprise Leadership, Cloud Ops, DevOps, FinOps, and Compliance teams.

==================================================================
MODULE 1: COST VISIBILITY & FINOPS INTELLIGENCE
==================================================================

(Keep all previously defined cost analytics and optimization requirements exactly as defined in the original architecture, including:)

- Daily / Monthly / 3 / 6 / 12 month cost views
- Grouping: Subscription, Resource Group, Resource Type, Service Category
- Drill-down visualization
- Idle VM detection
- Unattached disk detection
- SKU right-sizing recommendations
- Reserved Instance & Savings Plan optimization
- Savings estimation with confidence scoring
- Leadership, Ops, and Admin dashboards
- PDF reporting (scheduled & on-demand)
- SMTP notifications
- Azure AD (Entra ID) authentication
- RBAC roles (Admin, Write, Read)

==================================================================
MODULE 2: AKS OPERATIONS & CONTROL CENTER (NEW)
==================================================================

Create a new top-level navigation menu:
"AKS Operations"

This module must include:

--------------------------------------
A. CLUSTER INVENTORY VIEW
--------------------------------------
- List all AKS clusters across monitored subscriptions
- Display:
  - Cluster Name
  - Subscription
  - Resource Group
  - Kubernetes Version
  - Node Pools
  - Node Pool VM SKU
  - Node Pool Image Version
  - Node Labels
  - Provisioning state
- Support filtering & search
- Data retrieved using Managed Identity

--------------------------------------
B. DEPLOYMENT MANAGEMENT
--------------------------------------
- List deployments per namespace
- Show:
  - Replicas (desired vs available)
  - Image version
  - Resource requests/limits
- Provide UI action to:
  - Scale deployment (replica count adjustment)
  - Rolling restart deployment
- Enforce RBAC-based authorization

--------------------------------------
C. POD RESOURCE OBSERVABILITY
--------------------------------------
- Show CPU & Memory consumption per pod
- Graphical representation:
  - Time-series charts
  - Namespace filter
  - Deployment filter
- Data sources:
  - Azure Monitor / Container Insights
  - Kubernetes Metrics API
- Show:
  - Current usage
  - Requests vs Limits
  - Utilization percentage
- Identify over/under-utilized workloads

--------------------------------------
D. CRONJOB MANAGEMENT
--------------------------------------
- View all cronjobs across namespaces
- Display:
  - Schedule
  - Last run time
  - Status
  - Concurrency policy
- Provide:
  - Enable/Disable cronjob
  - Suspend/Resume option
  - Quick Create CronJob wizard:
      - Name
      - Namespace
      - Schedule (CRON expression)
      - Container image
      - Command
      - Resource requests/limits
- Enforce namespace-scoped RBAC

--------------------------------------
E. DATA PERSISTENCE
--------------------------------------
Use PostgreSQL for:
- Historical cluster metadata snapshots
- Deployment scaling history
- Pod utilization history (optional aggregation)
- Cronjob change audit history

Design DB schema with:
- Snapshot tables
- Change history tables
- Indexed checksum comparison tables

==================================================================
MODULE 3: COMPLIANCE & DRIFT DETECTION (NEW)
==================================================================

Create a new top-level navigation menu:
"Compliance & Drift Monitoring"

--------------------------------------
A. AZURE SYNAPSE PIPELINE CHECKSUM TRACKING
--------------------------------------
- Retrieve Synapse pipeline definitions via Azure SDK
- Generate SHA256 checksum of:
  - Pipeline JSON definition
- Store:
  - Pipeline name
  - Checksum
  - Timestamp
  - Subscription
- Compare today's checksum with yesterday’s
- Detect:
  - Added pipelines
  - Modified pipelines
  - Deleted pipelines
- Persist results in PostgreSQL
- Provide:
  - Drift summary dashboard
  - Change diff visualization
  - Audit export (PDF/CSV)

--------------------------------------
B. AKS POD CHECKSUM MONITORING
--------------------------------------
Generate checksum of:
- Pod spec
- Container image
- Environment variables
- Mounted volumes

Store:
- Pod name
- Namespace
- Cluster
- Checksum
- Timestamp

Detect:
- Image changes
- Config drift
- Secret reference changes
- Resource limit changes

Display:
- Drift timeline
- Compliance score
- Highlighted differences

==================================================================
TECHNICAL ARCHITECTURE
==================================================================

Provide:

1. High-level architecture diagram (described textually)
2. Microservices architecture:
   - Cost Service
   - AKS Service
   - Compliance Service
   - Reporting Service
   - Auth Service
3. PostgreSQL architecture
4. Data ingestion pipelines
5. Managed Identity for:
   - Azure Cost API
   - Azure Monitor
   - AKS
   - Synapse
6. Background workers (Celery / Async tasks) for checksum jobs

==================================================================
AKS DEPLOYMENT ARCHITECTURE
==================================================================

Design:

- AKS cluster topology
  - System node pool
  - User node pool
  - Auto-scaling
- Ingress (NGINX or AGIC)
- Workload Identity integration
- Azure Key Vault secret integration
- Horizontal Pod Autoscaler
- Pod Security Standards

==================================================================
CI/CD
==================================================================

Using Azure DevOps:

- Python build & unit tests
- Docker container build
- Security scanning
- Helm packaging
- Environment promotion
- Database migration strategy

==================================================================
SECURITY & GOVERNANCE
==================================================================

- Least privilege RBAC
- Namespace isolation
- Audit logging
- API rate limiting
- Secure scaling operations
- Compliance logging retention
- Encryption at rest (PostgreSQL)
- TLS everywhere

==================================================================
DELIVERABLES
==================================================================

Produce:

1. Architecture explanation
2. Service-level breakdown
3. API contracts (FastAPI endpoints)
4. PostgreSQL schema design
5. Sample Python backend code
6. Sample React components
7. Helm chart structure
8. CI/CD YAML pipelines
9. Checksum comparison logic
10. Drift detection algorithm
11. Security model
12. Extensibility strategy

The output must be:

- Enterprise-grade
- Production-ready
- Highly structured
- Suitable for CTO / Cloud Governance Board review
- Suitable for DevOps engineering execution

--------------------------------------------------------------------
Can you please Create a PPT of OpsPortal so that it can be presented to Leadership -

Include AT&T Theme
Include Target Audiance as Ops/Dev/Test Team
Advantage of different Modules Present in the Ops Portal
Tech Stack Details
---------------------------------------------------------------
Act as an extremely AI/ML architect who has deep expertise in converting a python fast API application (FAST API Services) into an agentic AI Solution using langchain and langgraph, Review our project - H:\ATTCC\GITHUB\apm0014313-attcc-ops-portal entirely without even skipping a single file or a line brainstorm and comeback with multiple option in converting this into Agentic AI Solution - give me pros and cons for each 
--------------------------------------------------------------
@workspace Act as an Expert Full-Stack Developer and Systems Architect.

I need to completely remove Redis from this entire application (`apm0014313-attcc-ops-portal`) and replace it with our primary Database for persistent data storage and fast loading.

Please perform a comprehensive codebase sweep and provide the step-by-step code changes and commands to achieve this. Do not miss any files or lines. 

Here are the specific requirements for this refactor:

1. **Complete Codebase Audit:** 
   - Search the entire workspace for any mention of `redis`, cache connections, Redis client instantiations, and Redis-specific commands (e.g., `get`, `set`, `hget`, `expire`).
   - Identify all files utilizing Redis (controllers, services, middleware, configuration files, environment variables, etc.).

2. **Replace Cache with Database:**
   - Refactor all identified cache logic to use our existing relational/NoSQL Database instead.
   - If Redis was used for session management or temporary tokens, provide the exact DB schema/table design needed to store this persistent data and the corresponding query logic.
   - Ensure the new DB queries are optimized for "fast load" (e.g., indexing recommendations).

3. **Dependency & Configuration Cleanup:**
   - Remove Redis dependencies from our package/dependency manager files (e.g., `package.json`, `pom.xml`, `requirements.txt`, etc.).
   - Update configuration files and environment variable templates (e.g., `.env.example`, `docker-compose.yml`, config folders) to remove Redis URLs/ports.

4. **Documentation & Tech Stack Updates:**
   - Update any `README.md`, developer instructions, setup guides, and tech stack documentation within the repository to explicitly remove Redis and document the new DB-driven approach.

Please provide the plan step-by-step, starting with the dependency/config removal, followed by the exact code changes needed for the services/controllers, and finally the documentation updates.
--------------------------------------------------------------
@workspace Act as an Expert Full Stack Developer and Systems Architect.

I need to implement an "Auto Sync" functionality for the **Leadership Dashboard** and the **Amortized Cost** modules so that data updates automatically without requiring a manual page refresh from the user. 

Please review the codebase and provide the step-by-step code changes required to achieve this, adhering strictly to the following requirements:

1. **Replicate Existing Patterns:**
   - Analyze the existing auto-sync implementation in the **Key Vault module** (including frontend polling/WebSockets, state management, and backend synchronization logic).
   - Implement the exact same architectural pattern and technologies for the Leadership Dashboard and Amortized Cost modules to maintain codebase consistency.

2. **Data Integrity & Environment Handling (Critical):**
   - This data is used for executive leadership reporting, so there is zero tolerance for missing, duplicate, or corrupt data.
   - Ensure the synchronization logic strictly separates and correctly processes both `prod` and `non-prod` environments. 
   - Implement appropriate transactional boundaries, error handling, or fallback mechanisms on the backend to guarantee data accuracy during the background sync.

3. **Strict Business Logic Filtering:**
   - The auto-sync process and the resulting queries MUST filter the cost and dashboard data based on Azure Subscriptions.
   - Only process and return data for Azure subscriptions that are explicitly marked as "enabled" or "monitored" within the Admin Control Panel settings.

**Deliverables requested:**
- Step 1: Identify the files associated with the Key Vault auto-sync to confirm you understand the pattern.
- Step 2: Provide the backend code changes (API endpoints, background jobs/cron, database queries with the required subscription filtering, and environment separation).
- Step 3: Provide the frontend code changes (React/Angular/Vue components, state updates, and auto-sync triggers) for the Leadership Dashboard and Amortized Cost modules.