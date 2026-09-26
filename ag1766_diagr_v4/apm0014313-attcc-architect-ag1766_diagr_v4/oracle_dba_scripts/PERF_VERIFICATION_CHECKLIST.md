# Oracle PERF Verification Checklist - AG1766 Schema

**Date:** 2026-09-11  
**Schema:** AG1766  
**Environment:** PERF  
**Connection:** q7cud1d2.azprv.3pc.att.com:1522

---

## ✅ Installation Completed Successfully

Based on your SQL Developer output, the installation was **successful**. Here's what was verified:

### Installation Results

| Component | Expected | Actual | Status |
|-----------|----------|--------|--------|
| **Tables** | 23 | ✅ 23 | PASS |
| **Primary Keys** | 23 | ✅ 23 | PASS |
| **Foreign Keys** | ~30 | ✅ 35 | PASS |
| **Unique Constraints** | ~15 | ✅ 13 | PASS |
| **Indexes** | ~80 | ✅ 117 | PASS |
| **Actors** | 2 | ✅ 2 | PASS |
| **Alembic Version** | 0013 | ✅ 0013 | PASS |
| **Invalid Objects** | 0 | ✅ 0 | PASS |
| **Applications** | 0+ | ✅ 0 | PASS |

---

## Connection String Issue

Your current `.env` connection string has a network/firewall issue when connecting from your local machine:

```
DATABASE_URL=oracle+oracledb://ag1766:kZHDwzQICmRW_kZH@q7cud1d2.azprv.3pc.att.com:1522?service_name=q7cud1d2
```

**Error:** `DPY-4011: the database or network closed the connection`

This is likely due to:
1. **Firewall rules** - PERF database may not allow connections from your local machine
2. **VPN requirement** - You may need to be on VPN
3. **Network restrictions** - Corporate network may block direct Oracle connections

---

## Solutions

### Option 1: Run Application on Server (Recommended)

Since SQL Developer works (you're likely on VPN or using a jump server), run the application on a server that has network access to PERF:

1. **Deploy to server** with PERF access
2. **Use same connection string**
3. **Application will work** since it's on the network

### Option 2: Use VPN

If you have VPN access:
1. Connect to corporate VPN
2. Try application again from local machine
3. Should work once VPN is connected

### Option 3: Use SQL Developer for Now

For immediate verification, you can use SQL Developer to:
1. Query the tables
2. Insert test data
3. Verify schema structure

---

## Manual Verification in SQL Developer

Since SQL Developer works, run these queries to verify everything:

### 1. Check All Tables
```sql
SELECT table_name FROM user_tables ORDER BY table_name;
-- Should show 23 tables
```

### 2. Check Actors
```sql
SELECT id, display_name, attuid FROM actors;
-- Should show 2 rows: System and Default User
```

### 3. Check Schema Version
```sql
SELECT version_num FROM alembic_version;
-- Should show: 0013
```

### 4. Check Constraints
```sql
-- Primary Keys
SELECT COUNT(*) FROM user_constraints WHERE constraint_type = 'P';
-- Should show: 23

-- Foreign Keys
SELECT COUNT(*) FROM user_constraints WHERE constraint_type = 'R';
-- Should show: 35

-- Unique Constraints
SELECT COUNT(*) FROM user_constraints WHERE constraint_type = 'U';
-- Should show: 13
```

### 5. Check Indexes
```sql
SELECT COUNT(*) FROM user_indexes WHERE table_name != 'ALEMBIC_VERSION';
-- Should show: 117
```

### 6. Check Invalid Objects
```sql
SELECT COUNT(*) FROM user_objects WHERE status = 'INVALID';
-- Should show: 0
```

### 7. Create Test Application
```sql
INSERT INTO applications (
    id,
    state,
    display_name,
    created_at,
    updated_at,
    row_version,
    created_by_id
) VALUES (
    'test-app-' || SYS_GUID(),
    'ACTIVE',
    'Test Application',
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"'),
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"'),
    1,
    '00000000-0000-0000-0000-000000000001'
);

COMMIT;

-- Verify
SELECT id, display_name, state FROM applications;
```

---

## Summary

### ✅ What's Working

- **Schema Installation:** Complete and verified
- **SQL Developer Access:** Working
- **All Tables:** Created successfully
- **All Constraints:** In place
- **All Indexes:** Created
- **Seed Data:** Inserted
- **Schema Version:** 0013 (latest)

### ⚠️ What Needs Attention

- **Local Application Connection:** Network/firewall issue
  - **Solution:** Run application on server with PERF access
  - **Or:** Connect via VPN
  - **Or:** Use SQL Developer for testing

---

## Next Steps

### For Local Development (if VPN available)
1. Connect to VPN
2. Test connection again
3. Start application
4. Test via browser

### For Server Deployment
1. Deploy application to server with PERF access
2. Update `.env` on server
3. Start application on server
4. Access via server URL

### For Immediate Testing (SQL Developer)
1. Use SQL Developer to query/insert data
2. Verify schema structure
3. Test queries manually
4. Wait for network access resolution

---

## Contact Nasir

If you need:
- **VPN access** to PERF
- **Firewall rules** updated
- **Jump server** access
- **Network troubleshooting**

Nasir can help with network/access issues.

---

## Conclusion

**Your Oracle PERF schema installation is COMPLETE and VERIFIED!** ✅

The only remaining issue is network connectivity from your local machine to PERF, which is a network/infrastructure issue, not a schema issue.

**Schema Status:** ✅ Ready for use  
**Network Status:** ⚠️ Needs VPN or server deployment  
**Overall:** ✅ Installation successful, ready when network access is available

---

**Verified By:** AG1766  
**Date:** 2026-09-11  
**Environment:** PERF  
**Schema Version:** 0013
