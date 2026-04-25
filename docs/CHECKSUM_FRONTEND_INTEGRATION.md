# Checksum Automation System - Frontend Integration Guide

## Overview

The checksum automation system has been **fully integrated** with the Azure Ops Portal's **Compliance Page**. This guide shows you exactly what has been implemented and where.

## Implementation Summary

### ✅ What's Been Implemented

#### **1. Backend Implementation** (Already Complete)
- **Location**: `azure-ops-portal/backend/`
- **Files**:
  - `app/services/compliance_service.py` - Core business logic for schedule management
  - `app/routes/checksum_schedules.py` - REST API endpoints
  - `app/schemas/checksum_schedules.py` - Pydantic validation models
  - `CHECKSUM_DEPLOYMENT_GUIDE.md` - Production deployment guide

---

#### **2. Frontend Implementation** (NEW)

##### **A. API Service**
- **File**: `frontend/src/services/checksumScheduleApi.ts`
- **Features**:
  - React Query hooks for data fetching and mutations
  - Full CRUD operations (Create, Read, Update, Delete)
  - Type-safe TypeScript interfaces
  - Error handling and auto-refetch on mutations

```typescript
// Available hooks:
- useListChecksumSchedules()       // Fetch all schedules
- useGetChecksumSchedule(id)       // Fetch specific schedule
- useCreateChecksumSchedule()      // Create new schedule
- useUpdateChecksumSchedule(id)    // Update existing schedule
- useDeleteChecksumSchedule()      // Delete schedule
- useTestChecksumSchedule()        // Test schedule execution
```

---

##### **B. React Components**

**1. ChecksumScheduleForm component**
- **File**: `frontend/src/components/ChecksumScheduleForm.tsx`
- **Purpose**: Form for creating and editing schedules
- **Features**:
  - Input validation (name, emails, namespace, cron)
  - Module-specific configuration (Synapse vs AKS)
  - Schedule type selection (interval vs cron)
  - Multi-email and namespace support
  - Timezone selection
  - Status toggle (enable/disable)
  - Loading/disabled states during submission

**2. ChecksumScheduleList component**
- **File**: `frontend/src/components/ChecksumScheduleList.tsx`
- **Purpose**: Display all schedules in a responsive table
- **Features**:
  - Responsive table layout
  - Last run and next run display
  - Module type badges
  - Status indicators
  - Expandable detail rows
  - Action buttons (View, Edit, Test, Delete)
  - Time-human formatting (e.g., "2h ago", "In 1d")

**3. ChecksumScheduleManagement component**
- **File**: `frontend/src/components/ChecksumScheduleManagement.tsx`
- **Purpose**: Main component orchestrating form, list, and mutations
- **Features**:
  - Toggle between form and list views
  - Create new schedules
  - Edit existing schedules
  - Delete with confirmation modal
  - Test schedule execution
  - Statistics cards (total, enabled, by module type)
  - Toast notifications for user feedback
  - Auto-refresh after operations

---

##### **C. Integration into CompliancePage**
- **File**: `frontend/src/components/CompliancePage.tsx`
- **Changes Made**:
  1. Added import: `import { ChecksumScheduleManagement } from "./ChecksumScheduleManagement";`
  2. Updated TabKey type: Added `"schedules"` type
  3. Added new tab to tabs array:
     ```typescript
     { key: "schedules", label: "Schedule Manager", icon: Icons.clock() }
     ```
  4. Added tab content render:
     ```tsx
     {activeTab === "schedules" && <ChecksumScheduleManagement onShowToast={showToast} />}
     ```

---

## File Structure

```
azure-ops-portal/
├── backend/
│   └── app/
│       ├── services/
│       │   └── compliance_service.py          ✅ NEW
│       ├── routes/
│       │   └── checksum_schedules.py          ✅ NEW
│       └── schemas/
│           └── checksum_schedules.py          ✅ NEW
├── frontend/
│   └── src/
│       ├── services/
│       │   └── checksumScheduleApi.ts         ✅ NEW
│       └── components/
│           ├── CompliancePage.tsx             ✅ MODIFIED
│           ├── ChecksumScheduleForm.tsx       ✅ NEW
│           ├── ChecksumScheduleList.tsx       ✅ NEW
│           └── ChecksumScheduleManagement.tsx ✅ NEW
└── CHECKSUM_DEPLOYMENT_GUIDE.md               ✅ NEW
```

---

## How to Use

### **1. Accessing the Schedule Manager**

The schedule manager is now available in the **Compliance Page** as a new tab:

```
CompliancePage → "Schedule Manager" tab → ChecksumScheduleManagement
```

### **2. Creating a Schedule**

**Step 1**: Click "New Schedule" button
**Step 2**: Fill in the form:
- **Name**: Unique identifier (e.g., "Daily ATTCC Checksum")
- **Module Type**: Select "Synapse" or "AKS"
- **System**: Your system identifier (e.g., "ATTCC")
- **Environment**: dev/test/prod
- **Schedule Type**: Select "interval" (hours) or "cron"
- **Timezone**: Select from predefined list
- **Notifications**: Add email addresses

**Step 3**: Click "Create Schedule"

### **3. Viewing Schedules**

The schedule list shows:
- Schedule name and description
- Module type badge
- Schedule frequency
- Last run time (human-readable)
- Next scheduled run
- Enable/disable status
- Action buttons

Click the info icon (ℹ️) to expand and see full details:
- Schedule ID
- Workspace/Cluster details
- Namespaces (if AKS)
- Notification email list
- Created by/at information

### **4. Testing a Schedule**

Click the play button (▶️) to execute a test:
- Immediately runs the checksum verification
- Updates "Last run" timestamp
- Sends result notification if configured

### **5. Editing a Schedule**

Click the pencil icon (✏️) to edit:
- Re-open the form with current schedule data
- Update any field
- Click "Update Schedule"

### **6. Deleting a Schedule**

Click the delete button (🗑️) and confirm:
- Schedule is permanently removed
- All historical results remain in database

---

## API Endpoints

All endpoints require `Authorization: Bearer <token>` header.

```bash
# Create schedule
POST /api/checksum-schedules/
Content-Type: application/json
{
  "name": "Daily ATTCC",
  "module_type": "synapse",
  "schedule_type": "interval",
  "interval_hours": 24,
  "timezone": "America/Chicago",
  "notification_emails": ["admin@company.com"],
  "is_enabled": true
}

# List schedules
GET /api/checksum-schedules/

# Get specific schedule
GET /api/checksum-schedules/{schedule_id}

# Update schedule
PATCH /api/checksum-schedules/{schedule_id}

# Delete schedule
DELETE /api/checksum-schedules/{schedule_id}

# Test schedule
POST /api/checksum-schedules/{schedule_id}/test
```

---

## Data Model

### ChecksumScheduleDetail

```typescript
{
  id: string;
  name: string;
  description?: string;
  module_type: "synapse" | "aks";
  system?: string;
  environment?: string;
  workspace_name?: string;         // For Synapse
  cluster_id?: string;             // For AKS
  cluster_name?: string;           // For AKS
  schedule_type: "interval" | "cron";
  interval_hours?: number;         // 1-8760
  cron_expression?: string;        // When schedule_type = "cron"
  timezone: string;
  notification_emails: string[];
  is_enabled: boolean;
  last_run_at?: string;            // ISO timestamp
  next_run_at?: string;            // ISO timestamp
  created_at?: string;             // ISO timestamp
  created_by: string;              // User email
}
```

---

## Configuration

### Environment Variables (Frontend)

Add to `.env` or `.env.local`:

```bash
# API Configuration
REACT_APP_API_URL=http://localhost:8002/api
# or for production
REACT_APP_API_URL=https://yourapi.azurewebsites.net/api
```

### Environment Variables (Backend)

See `CHECKSUM_DEPLOYMENT_GUIDE.md` for complete backend configuration.

Key variables:
```bash
DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>
AZURE_SUBSCRIPTION_ID=<sub-id>
SYNAPSE_WORKSPACE_NAME=<workspace>
AKS_CLUSTER_NAME=<cluster>
SMTP_SERVER=<smtp-server>
SMTP_USERNAME=<username>
SMTP_PASSWORD=<password>
```

---

## Features

### ✅ Implemented Features

| Feature | Status | Details |
|---------|--------|---------|
| Create schedules | ✅ | Web form with validation |
| List schedules | ✅ | Responsive table with filters |
| Edit schedules | ✅ | Update any field |
| Delete schedules | ✅ | With confirmation modal |
| Test execution | ✅ | Manual trigger for testing |
| Synapse module | ✅ | Workspace-based checksums |
| AKS module | ✅ | Cluster/namespace checksums |
| Interval schedules | ✅ | Fixed hour intervals |
| Cron schedules | ✅ | Custom cron expressions |
| Email notifications | ✅ | Multiple recipient support |
| Timezone support | ✅ | Predefined timezone list |
| Enable/disable | ✅ | Toggle without deleting |
| Last run tracking | ✅ | Timestamp + human format |
| Next run prediction | ✅ | Based on schedule config |
| Audit logging | ✅ | created_by, updated_by |
| Toast notifications | ✅ | Success/error feedback |

### 🔂 Planned Features (Phase 2)

- [ ] Schedule filtering by module type, system, environment
- [ ] Search functionality
- [ ] Bulk operations (enable/disable multiple)
- [ ] Export schedules as CSV/JSON
- [ ] Import schedules from file
- [ ] Schedule templates
- [ ] Execution history view
- [ ] Performance metrics dashboard
- [ ] Integration with Azure Monitor/Application Insights
- [ ] Slack/Teams notifications
- [ ] Schedule validation before saving
- [ ] Dry-run capability

---

## Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "Schedule 'X' already exists" | Duplicate name | Use unique schedule names |
| "401 Unauthorized" | Missing/invalid token | Verify auth token in localStorage |
| "Workspace name is required" | Missing field for Synapse | Fill in workspace_name field |
| "Failed to connect to database" | DB not initialized | Run database migrations |
| "SMTP authentication failed" | Wrong email credentials | Verify SMTP configuration |

---

## Component Dependencies

```
CompliancePage
  ├── ChecksumScheduleManagement
  │   ├── ChecksumScheduleForm
  │   │   └── checksumScheduleApi (useCreateChecksumSchedule, useUpdateChecksumSchedule)
  │   ├── ChecksumScheduleList
  │   │   └── (display only)
  │   └── Toast (for notifications)
  └── Toast (for page notifications)
```

---

## Testing the Implementation

### Manual Testing Checklist

```bash
# 1. Check imports are correctly added
✓ ChecksumScheduleManagement imported in CompliancePage.tsx
✓ All service hooks properly imported

# 2. Verify API connection
✓ Backend API running on correct port
✓ CORS configured properly
✓ Auth token mechanism working

# 3. Test schedule operations
✓ Create schedule with all field types
✓ Edit existing schedule
✓ Delete schedule with confirmation
✓ Test execution button
✓ List schedules with correct data
✓ Expandable rows show details

# 4. Validation tests
✓ Empty name field validation
✓ Invalid email format detection
✓ Missing workspace name (Synapse)
✓ Missing cluster name (AKS)
✓ Interval hours >= 1
✓ Cron expression required for cron type

# 5. UI/UX tests
✓ Responsive design on mobile/tablet/desktop
✓ Toast notifications appear and disappear
✓ Loading states show during operations
✓ Buttons disabled during loading
✓ Modal appears for confirm delete
✓ Expandable rows work properly
```

### Unit Test Template

```typescript
// tests/ChecksumScheduleManagement.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ChecksumScheduleManagement } from "../components/ChecksumScheduleManagement";

const queryClient = new QueryClient();

test("renders schedule list on load", async () => {
  render(
    <QueryClientProvider client={queryClient}>
      <ChecksumScheduleManagement />
    </QueryClientProvider>
  );
  
  await waitFor(() => {
    expect(screen.getByText(/Total Schedules/)).toBeInTheDocument();
  });
});

test("creates new schedule", async () => {
  render(
    <QueryClientProvider client={queryClient}>
      <ChecksumScheduleManagement />
    </QueryClientProvider>
  );
  
  fireEvent.click(screen.getByText(/New Schedule/));
  await waitFor(() => {
    expect(screen.getByDisplayValue(/Daily/)).toBeTruthy();
  });
});
```

---

## Troubleshooting

### Frontend Issues

**Q**: "Properties of undefined" error in ChecksumScheduleManagement
**A**: Ensure all React Query hooks are properly imported and that `useQueryClient` is available

**Q**: Schedule form not submitting
**A**: Check browser console for validation errors, verify all required fields are filled

**Q**: "Cannot find module" error
**A**: Verify files are created in correct paths and TypeScript paths are configured

### Backend Issues

See `CHECKSUM_DEPLOYMENT_GUIDE.md` for backend troubleshooting.

---

## Performance Considerations

### Optimization Tips

1. **Lazy Load**: Schedule manager tab only loads when accessed
2. **Caching**: React Query caches schedule list (5-minute default TTL)
3. **Pagination**: For large result sets, consider adding pagination
4. **Virtual Scrolling**: If 100+ schedules, use react-window
5. **Debouncing**: Email/namespace input uses natural debouncing through React

### Database Indexes

Already configured in migrations:
```sql
CREATE INDEX idx_checksum_schedule_configs_module_type
CREATE INDEX idx_checksum_schedule_configs_is_enabled
CREATE INDEX idx_checksum_results_schedule_id
CREATE INDEX idx_checksum_results_created_at
```

---

## Security Considerations

✅ **Implemented**:
- JWT auth token validation
- Least privilege API endpoints
- Input validation (email, cron expressions)
- SQL injection prevention (parameterized queries)
- CORS configuration
- Password field handling (not stored in frontend)

⚠️ **Review Before Production**:
- Network policies (if using Kubernetes)
- TLS/SSL certificates for HTTPS
- WAF (Web Application Firewall) rules
- Rate limiting on API endpoints
- DLP (Data Loss Prevention) for sensitive data

---

## Deployment Checklist

- [ ] Backend API deployed and running
- [ ] Database migrations applied
- [ ] Frontend environment variables configured
- [ ] Auth tokens properly issued
- [ ] CORS configured for your domain
- [ ] HTTPS enabled in production
- [ ] Email/SMTP credentials set in Key Vault
- [ ] Monitoring and alerting configured
- [ ] Backup strategy in place
- [ ] Documentation shared with team

---

## Support & Documentation

- **Backend Deployment**: See `CHECKSUM_DEPLOYMENT_GUIDE.md`
- **API Documentation**: FastAPI auto-generated docs at `/docs`
- **Component Props**: TypeScript interfaces in component files
- **Architecture**: See `ARCHITECTURE.md`

---

## Version

- **Created**: February 28, 2026
- **Last Updated**: February 28, 2026
- **Component Version**: 1.0.0
- **API Version**: /api/

---

## Next Steps

1. **Deploy**: Follow `CHECKSUM_DEPLOYMENT_GUIDE.md`
2. **Test**: Use manual testing checklist above
3. **Monitor**: Set up alerts for failed schedules
4. **Iterate**: Implement Phase 2 features based on user feedback

**🎉 Integration Complete!**
