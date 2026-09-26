# Migration Intake Application - User Guide

This guide explains how to use the Migration Intake web application for managing AWS Outposts migration data.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Applications](#applications)
3. [Intakes](#intakes)
4. [Questionnaire](#questionnaire)
5. [Evidence Management](#evidence-management)
6. [WaveUtil Server Data](#waveutil-server-data)
7. [Readiness and Freeze](#readiness-and-freeze)
8. [Export](#export)
9. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the Application

1. Open your web browser
2. Navigate to: `http://127.0.0.1:8000` (local) or your deployed URL
3. You will be redirected to the Applications list

### Navigation

The application follows a hierarchical structure:
```
Applications
  └── Intakes
        ├── Questionnaire (answers)
        ├── Evidence (uploaded files)
        ├── WaveUtil (server data)
        └── Readiness/Snapshot (freeze & export)
```

---

## Applications

### Viewing Applications

**URL:** `/applications`

The Applications page shows all registered applications in the system.

| Column | Description |
|--------|-------------|
| Name | Application display name |
| State | Current state (ACTIVE, ARCHIVED, etc.) |
| Created | When the application was registered |
| Actions | Links to manage the application |

### Creating a New Application

1. Navigate to `/applications`
2. Click **"New Application"** button
3. Fill in the form:
   - **Display Name**: Human-readable name (e.g., "Customer Portal v2")
   - **Identifier Type**: Type of ID (APM_ID, SNOW_CI, etc.)
   - **Identifier Value**: The actual identifier value
4. Click **"Create Application"**

The system will:
- Create the application record
- Automatically create an intake linked to the current catalog
- Redirect you to the intake page

### Viewing Application Details

**URL:** `/applications/{app_id}`

Shows:
- Application metadata
- List of intakes for this application
- Links to manage intakes

---

## Intakes

An **Intake** represents a single data collection effort for an application. Each intake is linked to a specific catalog version.

### Intake States

| State | Description |
|-------|-------------|
| DRAFT | Initial state, can be edited |
| IN_REVIEW | Under review, can still be edited |
| FROZEN | Locked, immutable snapshot created |
| CANCELLED | Abandoned, no longer active |
| SUPERSEDED | Replaced by a newer intake |

### Viewing Intake Details

**URL:** `/applications/{app_id}/intakes/{intake_id}`

Shows:
- Intake state and metadata
- Links to Questionnaire, Evidence, WaveUtil
- Readiness status (if applicable)

---

## Questionnaire

The questionnaire collects structured answers about the application.

### Accessing the Questionnaire

**URL:** `/applications/{app_id}/intakes/{intake_id}/questionnaire`

### Navigation

- Questions are organized into **Sections**
- Use the section tabs/links to navigate between sections
- Progress is shown for each section

### Answering Questions

Each question has a specific **response type**:

| Type | How to Answer |
|------|---------------|
| TEXT | Free-form text input |
| TEXTAREA | Multi-line text |
| YES_NO | Select Yes or No |
| YES_NO_NA | Select Yes, No, or N/A |
| SINGLE_SELECT | Choose one option from a list |
| MULTI_SELECT | Choose multiple options |
| INTEGER | Enter a whole number |
| DECIMAL | Enter a decimal number |
| DATE | Select a date |
| EMAIL | Enter an email address |
| URL | Enter a web URL |
| IP_ADDRESS | Enter an IP address |
| CIDR | Enter a CIDR block |
| PORT | Enter a port number |
| HOSTNAME | Enter a hostname |
| FILE_REFERENCE | Reference an uploaded file |

### Saving Answers

1. Fill in your answer
2. Click **"Save"** or the save button
3. The answer is saved immediately
4. A confirmation message appears

### Answer States

| State | Meaning |
|-------|---------|
| DRAFT | Initial answer, not reviewed |
| CONFIRMED | Reviewed and confirmed |
| NEEDS_REVIEW | Flagged for review |

---

## Evidence Management

Evidence includes uploaded files that support questionnaire answers.

### Accessing Evidence

**URL:** `/applications/{app_id}/intakes/{intake_id}/evidence`

### Evidence Sources Tab

Shows all uploaded evidence files:

| Column | Description |
|--------|-------------|
| Filename | Original uploaded filename |
| Type | Media type (Excel, PDF, etc.) |
| Size | File size |
| Uploaded | Upload timestamp |
| State | ACTIVE, QUARANTINED, etc. |

### Uploading Evidence

1. Click **"Upload Evidence"**
2. Select a file from your computer
3. Supported formats:
   - Excel workbooks (.xlsx, .xls)
   - CSV files (.csv)
   - PDF documents (.pdf)
   - Images (.png, .jpg)
4. Click **"Upload"**
5. The file is processed and stored

### Import Summary Tab

After uploading an Excel workbook, the import summary shows:
- Number of rows processed
- Candidates extracted
- Any errors or warnings

---

## WaveUtil Server Data

WaveUtil manages server/infrastructure data extracted from evidence.

### Accessing WaveUtil

**URL:** `/applications/{app_id}/intakes/{intake_id}/wave-util`

### WaveUtil List

Shows all server rows:

| Column | Description |
|--------|-------------|
| Server Name | Server identifier |
| Environment | PROD, DEV, TEST, etc. |
| Scope | IN_SCOPE, OUT_OF_SCOPE |
| State | ACTIVE, RETIRED |
| Actions | View, Edit, Retire |

### Viewing Server Details

**URL:** `/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}`

Shows:
- Server metadata
- Field values (CPU, memory, storage, etc.)
- Revision history
- Pending candidates (if any)

### Managing Candidates

When evidence is imported, the system creates **candidates** - proposed changes that need review.

#### Accepting Candidates

1. Navigate to the WaveUtil detail page
2. Review the pending candidates
3. Click **"Accept"** to apply the change
4. The canonical data is updated

#### Rejecting Candidates

1. Navigate to the WaveUtil detail page
2. Review the pending candidates
3. Click **"Reject"** to discard the change
4. The candidate is marked as rejected

### Retiring a Server

1. Navigate to the server detail page
2. Click **"Retire"**
3. Confirm the action
4. The server is marked as RETIRED (soft delete)

---

## Readiness and Freeze

Before exporting data, an intake must be **frozen** to create an immutable snapshot.

### Checking Readiness

**URL:** `/intakes/{intake_id}/readiness`

The readiness check evaluates multiple dimensions:

| Dimension | Description |
|-----------|-------------|
| intake_state | Must be DRAFT or IN_REVIEW |
| unresolved_candidates | All candidates must be accepted/rejected |
| deferred_candidates | Deferred candidates are allowed |
| snapshot_exists | Checks if already frozen |
| wave_util_completeness | WaveUtil data status |

#### Readiness Status

- **Ready to Freeze**: All dimensions pass, green indicators
- **Not Ready**: One or more dimensions fail, shows blockers

### Freezing an Intake

1. Navigate to `/intakes/{intake_id}/readiness`
2. Verify all dimensions show "Passed"
3. Click **"Freeze Intake"**
4. On success:
   - Intake state changes to FROZEN
   - Immutable snapshot is created
   - SHA-256 hash is computed
5. You're redirected to the success page

### Freeze Errors

If freeze fails, you'll see:
- List of blocking dimensions
- Specific blockers to resolve
- Link to check readiness again

### Idempotent Freeze

Freezing an already-frozen intake is safe:
- Returns the existing snapshot
- No duplicate snapshots created

---

## Export

After freezing, you can export the canonical data package.

### Viewing Snapshot

**URL:** `/intakes/{intake_id}/snapshot`

Shows:
- Snapshot ID
- Schema version
- SHA-256 hash (payload integrity)
- Catalog SHA-256 (catalog version)
- Creation timestamp
- Payload summary (answers, WaveUtil rows)

### Exporting the Package

**URL:** `/intakes/{intake_id}/export`

Downloads the canonical JSON package containing:
- Application identity
- Catalog version and hash
- All confirmed answers
- All active WaveUtil rows
- Permitted gaps (if any)

Response headers include:
- `X-Payload-SHA256`: Hash for verification
- `X-Schema-Version`: Schema version

### Exporting the Manifest

**URL:** `/intakes/{intake_id}/export/manifest.json`

Returns metadata about the export:
```json
{
  "format_version": "1.0.0",
  "export_timestamp": "2026-09-09T12:00:00.000Z",
  "snapshot_id": "...",
  "intake_id": "...",
  "payload_sha256": "...",
  "schema_version": "1.0.0"
}
```

---

## API Endpoints

For programmatic access, JSON APIs are available:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/intakes/{id}/readiness.json` | GET | Readiness status (JSON) |
| `/intakes/{id}/freeze.json` | POST | Freeze intake (JSON) |
| `/intakes/{id}/snapshot.json` | GET | Snapshot details (JSON) |
| `/intakes/{id}/export` | GET | Export package |
| `/intakes/{id}/export/manifest.json` | GET | Export manifest |
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |

### API Documentation

Interactive API documentation is available at:
- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`

(Only available in local/test environments)

---

## Troubleshooting

### Common Issues

#### "Intake not found"
- Verify the intake ID is correct
- Check if the intake exists in the database

#### "No snapshot found"
- The intake has not been frozen yet
- Navigate to `/intakes/{id}/readiness` to freeze

#### "Intake not ready to freeze"
- Review the blocking dimensions
- Resolve unresolved candidates
- Ensure intake state is DRAFT or IN_REVIEW

#### "CSRF token invalid"
- Refresh the page and try again
- Clear browser cookies if persistent

#### "Foreign key constraint failed"
- Ensure all referenced records exist
- Check actor, application, catalog records

### Health Checks

- **Liveness**: `/health/live` - Returns 200 if app is running
- **Readiness**: `/health/ready` - Returns 200 if database is accessible

### Logs

Application logs show:
- Request/response details
- Database operations
- Error stack traces

Log level is controlled by `LOG_LEVEL` environment variable.

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Tab | Navigate between form fields |
| Enter | Submit form / Save answer |
| Escape | Cancel current action |

---

## Browser Support

Tested and supported browsers:
- Chrome 90+
- Firefox 88+
- Edge 90+
- Safari 14+

JavaScript must be enabled for full functionality.

---

## Getting Help

- **Documentation**: See `docs/` folder
- **API Docs**: `/docs` endpoint
- **Support**: Contact the Migration Architecture Team
