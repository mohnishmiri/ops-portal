# Migration Intake - Quick Start Guide

Get up and running with the Migration Intake application in 5 minutes.

## Prerequisites

- Application running at `http://127.0.0.1:8000`
- Modern web browser (Chrome, Firefox, Edge, Safari)

---

## Step 1: Create an Application

1. Open your browser to `http://127.0.0.1:8000`
2. You'll see the **Applications** list (initially empty)
3. Click **"New Application"**
4. Fill in:
   - **Display Name**: `My Test Application`
   - **Identifier Type**: `APM_ID`
   - **Identifier Value**: `APM001`
5. Click **"Create Application"**

**Result**: Application created with an intake automatically started.

---

## Step 2: Navigate the Intake

After creating an application, you'll see the intake page with links to:

| Section | Purpose |
|---------|---------|
| **Questionnaire** | Answer questions about the application |
| **Evidence** | Upload supporting documents |
| **WaveUtil** | Manage server/infrastructure data |

---

## Step 3: Upload Evidence (Optional)

1. Click **"Evidence"** link
2. Click **"Upload Evidence"**
3. Select an Excel file (.xlsx) containing server data
4. Click **"Upload"**

**Result**: File is processed, candidates are extracted.

---

## Step 4: Review WaveUtil Data

1. Click **"WaveUtil"** link
2. View the list of servers extracted from evidence
3. Click on a server to see details
4. **Accept** or **Reject** any pending candidates

---

## Step 5: Answer Questionnaire (Optional)

1. Click **"Questionnaire"** link
2. Navigate through sections using tabs
3. Answer questions as needed
4. Click **"Save"** after each answer

---

## Step 6: Check Readiness

1. Navigate to: `/intakes/{intake_id}/readiness`
   - Or find the "Readiness" link on the intake page
2. Review the readiness dimensions:
   - All green = Ready to freeze
   - Any red = Resolve blockers first

---

## Step 7: Freeze the Intake

1. On the Readiness page, click **"Freeze Intake"**
2. Wait for confirmation
3. You'll see:
   - Snapshot ID
   - SHA-256 hash
   - Creation timestamp

**Result**: Intake is now immutable.

---

## Step 8: Export the Data

1. Click **"Export Package"** on the success page
2. Download the canonical JSON file
3. Or click **"View Manifest"** for metadata only

---

## Common URLs

| URL | Description |
|-----|-------------|
| `/` | Home (redirects to applications) |
| `/applications` | List all applications |
| `/applications/new` | Create new application |
| `/docs` | API documentation (Swagger) |
| `/health/live` | Health check |

---

## Workflow Summary

```
┌─────────────────┐
│ Create App      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Upload Evidence │ (optional)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Review WaveUtil │ (accept/reject candidates)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Answer Questions│ (optional)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Readiness │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Freeze Intake   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Export Package  │
└─────────────────┘
```

---

## Tips

1. **Save often**: Answers are saved individually
2. **Check readiness early**: Identify blockers before trying to freeze
3. **Review candidates**: Don't leave candidates in PROPOSED state
4. **Use the API docs**: `/docs` has interactive API testing

---

## Next Steps

- Read the full [User Guide](USER_GUIDE.md)
- Explore the [API Documentation](/docs)
- Review the [Architecture Documentation](../src/PRODUCTION_FOUNDATION_TDD_IMPLEMENTATION_PLAN.md)
