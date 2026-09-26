# Oracle Deployment Checklist

**Migration Intake Application - Production Deployment**

Use this checklist to ensure a successful Oracle deployment. Check off each item as you complete it.

---

## Pre-Deployment (1-2 days before)

### Environment Preparation

- [ ] **Oracle Database Available**
  - Version: Oracle 12c or later
  - Status: Running and accessible
  - Network: Firewall rules configured for port 1521

- [ ] **Database Credentials**
  - SYSDBA credentials obtained
  - Application user password generated (16+ characters)
  - Credentials stored in secrets manager

- [ ] **Application Server**
  - Python 3.12+ installed
  - Network access to Oracle database verified
  - Sufficient disk space (minimum 10GB)

- [ ] **Backup Plan**
  - Backup schedule defined
  - Backup storage configured
  - Restore procedure documented

### Code Preparation

- [ ] **Repository**
  - Latest code pulled from `origin/ag1766_diagr_v4`
  - Oracle integration changes merged
  - All tests passing locally

- [ ] **Dependencies**
  - `requirements.txt` updated
  - All dependencies available in package repository
  - No version conflicts

- [ ] **Configuration**
  - Environment variables documented
  - Configuration files prepared
  - Secrets management configured

---

## Deployment Day

### Phase 1: Database Setup (30 minutes)

- [ ] **1.1 Create Schema**
  ```bash
  sqlplus sys/password@SERVICE as sysdba @01_create_schema.sql
  ```
  - [ ] User `migration_intake` created
  - [ ] Privileges granted
  - [ ] Tablespace quota set

- [ ] **1.2 Update Password**
  ```sql
  ALTER USER migration_intake IDENTIFIED BY "production_password";
  ```
  - [ ] Strong password set
  - [ ] Password stored in secrets manager
  - [ ] Test connection successful

- [ ] **1.3 Verify Schema**
  ```sql
  SELECT username, account_status FROM dba_users WHERE username = 'MIGRATION_INTAKE';
  ```
  - [ ] User status: OPEN
  - [ ] Account not locked

---

### Phase 2: Application Setup (15 minutes)

- [ ] **2.1 Install Dependencies**
  ```bash
  pip install -e ".[dev]"
  ```
  - [ ] All packages installed successfully
  - [ ] No dependency conflicts
  - [ ] Version verification complete

- [ ] **2.2 Set Environment Variables**
  ```bash
  export DATABASE_URL='oracle+oracledb://migration_intake:password@host:1521?service_name=SERVICE'
  export EVIDENCE_ROOT='/path/to/evidence'
  export ACTOR_ID='00000000-0000-0000-0000-000000000001'
  export CSRF_SECRET='your-32-character-secret'
  ```
  - [ ] DATABASE_URL set correctly
  - [ ] EVIDENCE_ROOT directory exists
  - [ ] ACTOR_ID is valid UUID
  - [ ] CSRF_SECRET is 32+ characters

- [ ] **2.3 Test Database Connection**
  ```python
  python -c "from sqlalchemy import create_engine; import os; create_engine(os.environ['DATABASE_URL']).connect()"
  ```
  - [ ] Connection successful
  - [ ] No timeout errors
  - [ ] No authentication errors

---

### Phase 3: Run Migrations (15 minutes)

- [ ] **3.1 Execute Migration Script**
  ```bash
  chmod +x 02_run_migrations.sh
  ./02_run_migrations.sh
  ```
  - [ ] Pre-flight checks passed
  - [ ] All 12 migrations executed
  - [ ] No errors in output
  - [ ] Final version: 0012

- [ ] **3.2 Verify Migration Success**
  ```bash
  alembic current
  ```
  - [ ] Output: `0012 (head)`
  - [ ] No warnings

- [ ] **3.3 Check Table Creation**
  ```sql
  SELECT COUNT(*) FROM user_tables;
  ```
  - [ ] Expected: 23 tables
  - [ ] All tables present

---

### Phase 4: Verification (20 minutes)

- [ ] **4.1 Run Verification Script**
  ```bash
  sqlplus migration_intake/password@SERVICE @03_verify_deployment.sql
  ```
  - [ ] Alembic version: 0012
  - [ ] All 23 tables exist
  - [ ] All primary keys defined
  - [ ] All foreign keys defined
  - [ ] All unique constraints defined
  - [ ] No constraint names >30 characters
  - [ ] All CLOB columns present
  - [ ] No invalid objects
  - [ ] Smoke test passed

- [ ] **4.2 Run Application Tests**
  ```bash
  export ORACLE_TEST_URL="$DATABASE_URL"
  python -m pytest tests/contract/persistence/ -v -k "not migration_idempotency"
  ```
  - [ ] All repository tests passing
  - [ ] No connection errors
  - [ ] No LOB handle leaks

---

### Phase 5: Application Startup (10 minutes)

- [ ] **5.1 Start Application**
  ```bash
  uvicorn migration_intake.main:get_app --factory --host 0.0.0.0 --port 8000
  ```
  - [ ] Application started successfully
  - [ ] No startup errors
  - [ ] Listening on port 8000

- [ ] **5.2 Test Health Endpoints**
  ```bash
  curl http://localhost:8000/health/live
  curl http://localhost:8000/health/ready
  ```
  - [ ] Liveness: `{"status":"ok"}`
  - [ ] Readiness: Status appropriate for environment

- [ ] **5.3 Test Basic Functionality**
  - [ ] Can access web interface
  - [ ] Can create test actor
  - [ ] Can create test application
  - [ ] Database writes successful

---

### Phase 6: Monitoring Setup (15 minutes)

- [ ] **6.1 Configure Monitoring**
  - [ ] Application logs configured
  - [ ] Database monitoring enabled
  - [ ] Alert thresholds set
  - [ ] Notification channels configured

- [ ] **6.2 Verify Monitoring**
  - [ ] Logs are being written
  - [ ] Metrics are being collected
  - [ ] Alerts are working
  - [ ] Dashboard is accessible

---

### Phase 7: Documentation (10 minutes)

- [ ] **7.1 Update Documentation**
  - [ ] Deployment date recorded
  - [ ] Database version documented
  - [ ] Configuration documented
  - [ ] Known issues documented

- [ ] **7.2 Handoff**
  - [ ] Operations team notified
  - [ ] Support team briefed
  - [ ] Runbook updated
  - [ ] Contact information current

---

## Post-Deployment (24 hours after)

### Monitoring

- [ ] **Application Health**
  - [ ] No errors in logs
  - [ ] Response times normal
  - [ ] No memory leaks
  - [ ] No connection pool exhaustion

- [ ] **Database Health**
  - [ ] No long-running queries
  - [ ] No table locks
  - [ ] No LOB segment growth issues
  - [ ] Backup completed successfully

### Performance

- [ ] **Baseline Metrics**
  - [ ] Average response time: _____ms
  - [ ] Requests per second: _____
  - [ ] Database connections: _____
  - [ ] Memory usage: _____MB

- [ ] **Load Testing** (if applicable)
  - [ ] Load test executed
  - [ ] Performance acceptable
  - [ ] No bottlenecks identified

---

## Rollback Plan

### If Deployment Fails

- [ ] **1. Stop Application**
  ```bash
  pkill -f uvicorn
  ```

- [ ] **2. Document Issue**
  - [ ] Error messages captured
  - [ ] Logs saved
  - [ ] Screenshots taken

- [ ] **3. Rollback Database** (if needed)
  ```bash
  alembic downgrade <previous_version>
  ```

- [ ] **4. Restore from Backup** (if needed)
  ```bash
  impdp migration_intake/password@SERVICE schemas=migration_intake ...
  ```

- [ ] **5. Notify Stakeholders**
  - [ ] Team notified
  - [ ] Management informed
  - [ ] Post-mortem scheduled

---

## Sign-Off

### Deployment Team

- [ ] **Database Administrator**
  - Name: ________________
  - Date: ________________
  - Signature: ________________

- [ ] **Application Developer**
  - Name: ________________
  - Date: ________________
  - Signature: ________________

- [ ] **Operations Lead**
  - Name: ________________
  - Date: ________________
  - Signature: ________________

### Approvals

- [ ] **Technical Lead**
  - Name: ________________
  - Date: ________________
  - Signature: ________________

- [ ] **Product Owner**
  - Name: ________________
  - Date: ________________
  - Signature: ________________

---

## Notes

### Issues Encountered

_Document any issues encountered during deployment and how they were resolved._

---

### Lessons Learned

_Document any lessons learned for future deployments._

---

### Next Steps

_Document any follow-up actions required._

---

**Deployment Status:** ⬜ Not Started | ⬜ In Progress | ⬜ Complete | ⬜ Rolled Back

**Deployment Date:** ________________

**Deployment Time:** ________________

**Deployed By:** ________________
