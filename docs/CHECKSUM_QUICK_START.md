# Checksum Automation - Where Everything Is Located

## 📍 Frontend Integration Map

### Step 1: Access Compliance Page
```
Browser → Azure Ops Portal
         → Sidebar → Compliance Page
```

### Step 2: New Tab Appears
```
┌─────────────────────────────────────────────────────────────┐
│  Compliance & Drift Detection                              │
├─────────────────────────────────────────────────────────────┤
│  [Dashboard]  [Synapse Drift]  [AKS Drift]  [Timeline]     │
│  [Checksum Verify]  [Schedule Manager] ← NEW TAB           │
└─────────────────────────────────────────────────────────────┘
```

### Step 3: Click "Schedule Manager" Tab
```
Opens ChecksumScheduleManagement component which displays:

┌─────────────────────────────────────────────────────────────┐
│  Checksum Schedule Management                              │
│  Manage automated checksum verification...                 │
│                                          [+ New Schedule]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌────────┐  ┌────────┐│
│  │   Total     │  │  Enabled    │  │Synapse │  │  AKS   ││
│  │ Schedules   │  │             │  │        │  │        ││
│  │     3       │  │     2       │  │   2    │  │   1    ││
│  └─────────────┘  └─────────────┘  └────────┘  └────────┘│
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  Schedules (3)                              [Refresh]      │
├─────────────────────────────────────────────────────────────┤
│  Name              Module  Schedule    Last Run  Actions   │
│  ─────────────────────────────────────────────────────────  │
│  Daily ATTCC       SYNAPSE Every 24h   2h ago   [ℹ▶✏🗑]   │
│  Weekly Report     AKS     0 0 * * 0   Never    [ℹ▶✏🗑]   │
│  Hourly Check      SYNAPSE Every 1h    5m ago   [ℹ▶✏🗑]   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 File Locations

### Frontend Files
```
azure-ops-portal/frontend/src/
├── services/
│   └── checksumScheduleApi.ts          ← API hooks (useListChecksumSchedules, etc.)
│
└── components/
    ├── CompliancePage.tsx              ← MODIFIED (added "Schedule Manager" tab)
    ├── ChecksumScheduleManagement.tsx  ← Main orchestrator component
    ├── ChecksumScheduleForm.tsx        ← Form for create/edit
    └── ChecksumScheduleList.tsx        ← Table display
```

### Backend Files
```
azure-ops-portal/backend/app/
├── services/
│   └── compliance_service.py           ← Business logic (CRUD operations)
│
├── routes/
│   └── checksum_schedules.py           ← API endpoints
│
└── schemas/
    └── checksum_schedules.py           ← Data validation models
```

### Documentation Files
```
azure-ops-portal/
├── CHECKSUM_DEPLOYMENT_GUIDE.md        ← How to deploy to production
├── CHECKSUM_FRONTEND_INTEGRATION.md    ← This integration guide (detailed)
└── CHECKSUM_QUICK_START.md             ← This file (visual guide)
```

---

## 🔄 Data Flow

```
┌──────────────────────┐
│   CompliancePage     │ (existing page)
│   • Has tabs         │
│   • activeTab state  │
│   • showToast method │
└──────────────┬───────┘
               │
               ├─ activeTab === "schedules"
               │
               ▼
┌──────────────────────────────────────────┐
│   ChecksumScheduleManagement             │ (main component)
│   • Manages form/list toggle             │
│   • Handles mutations                    │
│   • Shows toast notifications            │
└──────────────┬──────────────────────────┘
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
   ┌────────────┐  ┌──────────────┐
   │    Form    │  │     List     │
   │ (Create/   │  │ (Display all │
   │  Edit)     │  │  schedules)  │
   └────┬───────┘  └──────┬───────┘
        │                 │
        └────────┬────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │  checksumScheduleApi.ts         │
    │  React Query Hooks              │
    │  • useCreateChecksumSchedule()  │
    │  • useListChecksumSchedules()   │
    │  • useUpdateChecksumSchedule()  │
    │  • useDeleteChecksumSchedule()  │
    │  • useTestChecksumSchedule()    │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │  Backend API                    │
    │  /api/checksum-schedules/       │
    │  • POST (create)                │
    │  • GET (list)                   │
    │  • PATCH (update)               │
    │  • DELETE (delete)              │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │  compliance_service.py          │
    │  Business logic                 │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │  PostgreSQL Database            │
    │  checksum_schedule_configs      │
    │  checksum_results               │
    └─────────────────────────────────┘
```

---

## 🎨 Component Tree

```
CompliancePage
│
├── Toast (notifications)
│
└── [Tabs UI]
    ├── Dashboard Tab
    ├── Synapse Drift Tab
    ├── AKS Pod Drift Tab
    ├── Drift Timeline Tab
    ├── Checksum Verify Tab
    └── [Schedule Manager Tab] ← NEW
        │
        └── ChecksumScheduleManagement
            │
            ├── When showForm = false
            │   │
            │   ├── ChecksumScheduleList
            │   │   ├── Table headers
            │   │   ├── Table rows (with action buttons)
            │   │   └── Expandable detail rows
            │   │
            │   └── Stats Cards
            │       ├── Total Schedules
            │       ├── Enabled Schedules
            │       ├── Synapse Schedules
            │       └── AKS Schedules
            │
            ├── When showForm = true
            │   │
            │   └── ChecksumScheduleForm
            │       ├── Basic Information
            │       │   ├── Schedule Name
            │       │   ├── Module Type
            │       │   ├── System
            │       │   └── Environment
            │       │
            │       ├── Module Configuration
            │       │   ├── Synapse: Workspace Name
            │       │   └── AKS: Cluster ID, Cluster Name, Namespaces
            │       │
            │       ├── Schedule Configuration
            │       │   ├── Schedule Type (interval/cron)
            │       │   ├── Interval Hours OR Cron Expression
            │       │   └── Timezone
            │       │
            │       └── Notifications
            │           └── Notification Emails
            │
            └── Delete Confirmation Modal
                ├── Confirmation message
                ├── Cancel button
                └── Delete button
```

---

## 🔐 Authentication Flow

```
1. User logs into Azure Ops Portal
   └─ Browser stores auth token in localStorage

2. User navigates to Compliance Page
   └─ Page loads and renders tabs (including Schedule Manager)

3. User clicks Schedule Manager tab
   └─ ChecksumScheduleManagement mounts
   └─ calls useListChecksumSchedules()

4. React Query hook prepares request
   └─ Calls checksumScheduleApi.listSchedules()
   └─ Gets token from localStorage
   └─ Adds Authorization header: "Bearer {token}"

5. API request sent to /api/checksum-schedules/
   └─ Backend validates token
   └─ Returns list of schedules
   └─ React Query caches results

6. Component re-renders with schedule list
   └─ User can now create/edit/delete/test schedules
```

---

## 📊 Example: Creating a Schedule

### User Actions (What You See)

```
1. Click [+ New Schedule] button
   ↓
2. Form appears with fields:
   - Name: "Daily ATTCC Checksum"
   - Module Type: "Synapse"
   - System: "ATTCC"
   - Environment: "prod"
   - Workspace Name: "attcc-workspace"
   - Schedule Type: "interval"
   - Interval Hours: 24
   - Timezone: "America/Chicago"
   - Notification Emails: [admin@company.com]
   - Status: Enabled ✓
   ↓
3. Click [Create Schedule] button
   ↓
4. Form disables, shows "Saving..."
   ↓
5. Success toast appears: "Schedule created successfully"
   ↓
6. Form closes, list updates with new schedule
   ↓
7. Schedule appears in table with "Last Run: Never"
```

### Behind the Scenes (Code Flow)

```
ChecksumScheduleForm.handleSubmit()
  ↓ (validate inputs)
  ↓
ChecksumScheduleManagement.handleFormSubmit()
  ↓
createMutation.mutateAsync(data)
  ↓
checksumScheduleApi.createSchedule(data)
  ↓
axios.post("/api/checksum-schedules/", data, {
  headers: { Authorization: "Bearer {token}" }
})
  ↓
Backend: checksum_schedules.py / create_checksum_schedule()
  ↓
compliance_service.create_checksum_schedule()
  ↓
INSERT INTO checksum_schedule_configs (...)
  ↓
onSuccess callback triggered
  ↓
queryClient.invalidateQueries({ queryKey: ["checksumSchedules"] })
  ↓
useListChecksumSchedules re-fetches
  ↓
ChecksumScheduleList re-renders with new schedule
```

---

## 🔍 How to Verify Integration

### Check 1: Files Exist
```bash
# Frontend files
ls -la azure-ops-portal/frontend/src/services/checksumScheduleApi.ts
ls -la azure-ops-portal/frontend/src/components/ChecksumScheduleForm.tsx
ls -la azure-ops-portal/frontend/src/components/ChecksumScheduleList.tsx
ls -la azure-ops-portal/frontend/src/components/ChecksumScheduleManagement.tsx

# Backend files
ls -la azure-ops-portal/backend/app/services/compliance_service.py
ls -la azure-ops-portal/backend/app/routes/checksum_schedules.py
ls -la azure-ops-portal/backend/app/schemas/checksum_schedules.py

# Documentation
ls -la azure-ops-portal/CHECKSUM_DEPLOYMENT_GUIDE.md
ls -la azure-ops-portal/CHECKSUM_FRONTEND_INTEGRATION.md
```

### Check 2: Frontend Build
```bash
cd azure-ops-portal/frontend

# Install dependencies
npm install

# Check TypeScript errors
npx tsc --noEmit

# Build frontend
npm run build

# Start dev server
npm run dev
```

### Check 3: Backend API
```bash
cd azure-ops-portal/backend

# Check Python syntax
python -m py_compile app/services/compliance_service.py
python -m py_compile app/routes/checksum_schedules.py
python -m py_compile app/schemas/checksum_schedules.py

# Start API server
uvicorn app.main:app --reload --port 8002

# Visit http://localhost:8002/docs for API documentation
```

### Check 4: Integration in CompliancePage
```bash
# Verify import added
grep "ChecksumScheduleManagement" azure-ops-portal/frontend/src/components/CompliancePage.tsx

# Verify tab added
grep '"schedules"' azure-ops-portal/frontend/src/components/CompliancePage.tsx

# Verify tab content render
grep 'activeTab === "schedules"' azure-ops-portal/frontend/src/components/CompliancePage.tsx
```

---

## 🚀 Quick Start (after deployment)

```
1. Deploy backend:
   cd azure-ops-portal/backend
   docker build -t checksum-api:1.0.0 .
   kubectl apply -f kubernetes/deployment.yaml

2. Run database migrations:
   psql -h <host> -U <user> -d <db> -f migrations/001_create_checksum_schedules.sql

3. Deploy frontend:
   cd azure-ops-portal/frontend
   npm build
   Deploy dist/ to Azure Static Web App or CDN

4. Access compliance page:
   https://your-app/compliance
   Click "Schedule Manager" tab
   Create your first schedule!
```

---

## 📚 Documentation Files

| File | Purpose | Location |
|------|---------|----------|
| CHECKSUM_DEPLOYMENT_GUIDE.md | Production deployment steps | `/azure-cost-portal/` |
| CHECKSUM_FRONTEND_INTEGRATION.md | Complete frontend guide | `/azure-cost-portal/` |
| This file | Visual quick reference | `/azure-cost-portal/` |

---

## ✅ Summary

**What has been delivered:**

- ✅ Complete backend API (3 files)
- ✅ Complete frontend UI (4 files)
- ✅ Integration into CompliancePage
- ✅ Type-safe TypeScript interfaces
- ✅ React Query data management
- ✅ Form validation and error handling
- ✅ Toast notifications
- ✅ Responsive design
- ✅ Production deployment guide
- ✅ Frontend integration guide
- ✅ This quick reference guide

**You can now:**

1. ✅ Access Schedule Manager tab in Compliance Page
2. ✅ Create checksum schedules for Synapse and AKS
3. ✅ Edit, test, and delete schedules
4. ✅ Monitor schedule execution
5. ✅ Configure email notifications
6. ✅ Deploy to production following the guide

**Ready for production deployment!** 🎉
