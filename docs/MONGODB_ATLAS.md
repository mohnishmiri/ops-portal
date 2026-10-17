# MongoDB Atlas module

The **MongoDB Atlas** page (`/mongodb-atlas`) lets support teams stop and start
Atlas clusters, put them on start/stop schedules with email alerts, watch CPU
and memory, and administer Atlas projects. It does all of this through **one
Atlas API key that the portal holds**. Users never get an Atlas credential.

---

## 1. Go-live checklist

1. **Create a programmatic API key** in Atlas (Organization → Access Manager →
   API Keys). Give it only these roles, and only on the projects the portal
   should manage:

   | Atlas role | What the portal needs it for |
   |---|---|
   | Project Cluster Manager | Stop/start, tier change, test failover |
   | Project Owner | Database users and the IP access list |
   | Project Backup Creator / Project Alerts Manager | On-demand snapshots and acknowledging alerts (Project Owner already covers these) |

   Organization Read Only is enough at org level. A key with fewer roles still
   works: the actions it lacks fail with a clear message, and the audit log
   records the failure.

2. **Allow the portal's outbound IP** on the key's API access list. This is
   needed when the organization requires one, which is the default for orgs
   created in the UI. If the IP is missing, every call fails with 403. The
   *Administration* tab shows the address Atlas sees (`Portal's outbound IP`).

3. **Store the key in Key Vault**, then enable the `mongodbAtlas` group in the
   Helm values:

   | Key Vault secret | Env var |
   |---|---|
   | `opsportal-backend-mongodb-atlas-public-key` | `MONGODB_ATLAS_PUBLIC_KEY` |
   | `opsportal-backend-mongodb-atlas-private-key` | `MONGODB_ATLAS_PRIVATE_KEY` |

   Optional settings in `backend.env`:
   - `MONGODB_ATLAS_ORG_ID` limits the portal to one organization.
   - `MONGODB_ATLAS_PROJECT_IDS` is an allow-list. The portal refuses any other
     project, even if the key can see it.
   - `MONGODB_ATLAS_CA_BUNDLE` points at a CA file, for when a TLS-inspecting
     proxy sits in front of `cloud.mongodb.com`.

4. **Deploy.** The two tables (`atlas_schedules`, `atlas_operations`) are
   created on startup. `backend/migrations/add_mongodb_atlas.sql` is provided
   for out-of-band schema management.

5. **Grant access** in Admin → Permissions:
   - The `mongodb_atlas` module and the `mongodb_atlas_main` page are seeded:
     view for Read, view + edit for Write.
   - No Azure subscription grant is needed. Atlas projects are not Azure
     subscriptions.

6. **Classify clusters.** Tag each cluster in Atlas with `environment=prod` or
   `environment=nonprod`. Without a tag, the portal guesses from the cluster
   and project names. A cluster it cannot classify is treated as production.

---

## 2. Who can do what

Reads (inventory, utilization, schedules, activity, database users, access
list, alerts, audit log) are open to everyone with the module.

Each change needs the **Write** role **and** a capability. Each capability can
be revoked on its own in the Permissions matrix:

| Capability | Allows |
|---|---|
| `atlas_cluster_power` | Stop (pause) and start (resume) |
| `atlas_schedule_manage` | Create, edit, enable, skip and delete schedules. *Run now* also needs `atlas_cluster_power`. |
| `atlas_cluster_admin` | Tier change, test failover, on-demand snapshot, alert acknowledge |
| `atlas_database_access` | Database users (create, reset password, delete) and the IP access list |

**Production safeguards:**
- Stopping a production or unclassified cluster requires typing its name.
  The same applies to a tier change or a test failover.
- A schedule that includes one needs an explicit acknowledgment.
- The API enforces both rules, not just the UI.

---

## 3. How stop/start and schedules behave

**Atlas rules the portal applies before calling Atlas:**
- Only **M10+** clusters can be paused. NVMe, Free, Flex and Serverless
  clusters cannot.
- A cluster resumed less than **60 minutes** ago cannot be paused. The
  schedule editor rejects a stop less than an hour after a start.
- Atlas **resumes a cluster by itself after 30 days paused**. The page warns
  from day 25.
- While a cluster is paused, Atlas bills storage only.

**How an operation is tracked:**
- Every stop/start, manual or scheduled, becomes an *operation*.
- Atlas accepts the request at once, then takes minutes to finish it.
- A background tick checks each cluster every minute until it is IDLE in the
  new state.
- If a cluster has not finished after `MONGODB_ATLAS_OPERATION_TIMEOUT_MINUTES`
  (default 60), the operation reports it as failed.

**Schedules:**
- A schedule has a **stop** leg and a **start** leg; either one is optional.
  Each leg is recurring (cron, read in the schedule's timezone) or one-time.
- **Skip next stop/start** skips only that one run. It is recorded as skipped,
  then the schedule carries on.
- **Run now** runs a leg immediately. The schedule's timetable is unchanged.
- **Missed runs:** if the portal was down across both a stop and the next
  start, only the later one runs. The earlier one is recorded as skipped.
- **Multiple replicas:** every uvicorn worker on every replica runs the
  1-minute ticks. Compare-and-swap claims in PostgreSQL make sure each run,
  each operation check and each email happens exactly once.

**Emails:**
- **Summary:** sent once the operation has finished, listing the outcome for
  each cluster.
  - Scheduled runs go to the schedule's creator plus its "Also send to" list.
  - Manual stop/starts go to the requester, if they ticked the box, plus any
    extra addresses they gave.
  - The *Email a summary* setting chooses when: every run, failures only, or
    never.
- **Heads-up:** sent N minutes before a scheduled run (15 min to 1 day), with
  instructions to skip that run.

---

## 4. Audit

Every change is written to `audit_logs` with `resource_type = "mongodb_atlas"`,
including refused attempts:
- stop/start: one row when requested, one when finished
- schedules: create, edit, skip, delete
- tier change, test failover, snapshots
- alert acknowledge
- database users and IP access list

Database-user passwords are never recorded. A generated password is returned
once to the person who created or reset the user, and the portal does not keep
it. The page's **Audit log** tab shows these rows and can export them to CSV.

---

## 5. Atlas API details (verified against the Admin API v2 spec, Oct 2026)

**Base URL and auth:** `https://cloud.mongodb.com/api/atlas/v2`, HTTP Digest.
Each request names its resource version in the `Accept` header:

| Version | Used for |
|---|---|
| `2024-08-05` | Clusters, GET |
| `2024-10-23` | Clusters, PATCH (pause/resume and tier) |
| `2023-02-01` | `restartPrimaries` |
| `2024-05-30` | Alert acknowledge |
| `2023-01-01` | Everything else |

The backend logs `atlas_api_version_deprecated` when Atlas announces a sunset.

**Memory** is computed as used ÷ (used + available). Atlas publishes no memory
percentage metric.

**Mapping processes to clusters.** Atlas does not say which cluster a process
belongs to. The portal matches each process's host name against the cluster's
connection string. This is inferred, not documented by Atlas. If a cluster's
charts say *No monitored processes matched*, this matching is the place to
look.

**Not yet exercised against a live Atlas organization:** every call above,
especially the tier-change PATCH. The tests run against a simulated Atlas API.
