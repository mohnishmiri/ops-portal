# 🚀 START HERE - AG1766 Personal Schema Installation

**Your Schema:** AG1766  
**Environment:** PERF  
**Time Required:** 5 minutes  
**Difficulty:** ⭐ Easy

---

## Quick Start (4 Steps)

### 1️⃣ Open SQL Developer
- Connect to PERF as AG1766
- Verify you're connected (check schema name in top left)

### 2️⃣ Run These 4 Scripts (in order)
```
@02_create_tables.sql      ← Creates 23 tables
@03_create_indexes.sql     ← Creates ~80 indexes  
@04_seed_data.sql          ← Inserts 2 actors + version
@05_verify_schema.sql      ← Checks everything
```

**How to run in SQL Developer:**
- File → Open → Select script
- Press F5 (or click "Run Script" button)
- Check output for "complete!" message
- Repeat for next script

### 3️⃣ Update Application .env File
```bash
DATABASE_URL=oracle+oracledb://ag1766:YOUR_PASSWORD@perf-host:1521?service_name=PERFDB
```

Replace:
- `YOUR_PASSWORD` → Your AG1766 password
- `perf-host` → PERF database hostname
- `PERFDB` → PERF service name

### 4️⃣ Start Application & Test
```bash
python -m uvicorn migration_intake.main:get_app --factory --reload --port 8000
```

Then:
- Go to http://localhost:8000/applications
- Create a test application
- Test legacy intake upload!

---

## Expected Results

After running scripts, you should have:

✅ 23 tables in AG1766 schema  
✅ ~80 indexes  
✅ 2 actors (System, Default)  
✅ Schema version: 0013  
✅ 0 invalid objects  
✅ Application connects successfully  

---

## Troubleshooting

### ❌ "Table already exists"
**Solution:** Tables from previous run. Drop them first:
```sql
DROP TABLE applications CASCADE CONSTRAINTS;
-- Or drop all migration intake tables (see PERSONAL_SCHEMA_README.md)
```

### ❌ "Insufficient privileges"
**Solution:** Verify you have CREATE TABLE privilege:
```sql
SELECT * FROM user_sys_privs WHERE privilege LIKE '%CREATE%';
```

### ❌ "No space left"
**Solution:** Check your quota:
```sql
SELECT * FROM user_ts_quotas;
-- You should have 2GB in USERS tablespace
```

### ❌ Application won't connect
**Checklist:**
- [ ] Connection string in .env is correct
- [ ] Password is correct
- [ ] Can connect via SQL Developer
- [ ] Service name is correct
- [ ] Tables exist in AG1766 schema

---

## What You're Creating

**23 Tables:**
- Applications & Identifiers
- Intakes & Snapshots
- Questions & Answers
- Evidence & Imports
- Candidates & Findings
- Wave Utility
- Audit Trail

**~80 Indexes:**
- Foreign key indexes
- Performance indexes
- Composite indexes

**Seed Data:**
- System actor
- Default user actor
- Schema version marker

---

## Need More Details?

📖 **Full Guide:** `PERSONAL_SCHEMA_README.md`  
✅ **Checklist:** `INSTALLATION_CHECKLIST_AG1766.md`  
🔧 **Commands:** `QUICK_REFERENCE.md`  
❓ **Issues:** Check troubleshooting section above

---

## After Installation

### Test the Application
1. Create an application
2. Add identifiers (Correlation, MOTS, iTAP)
3. Create an intake
4. Upload evidence via lane ③ (Legacy intake)
5. Verify candidates are created

### Share with Team (Optional)
If others need access to your schema:
```sql
-- Grant read access
GRANT SELECT ON applications TO other_user;
GRANT SELECT ON intakes TO other_user;
-- etc.
```

### Migrate to Dedicated Schema (Later)
If you need a dedicated schema:
1. Export your data
2. Send scripts to Nasir
3. Import to new schema

---

## Summary

You have everything you need! Just:
1. ✅ Run 4 scripts in SQL Developer (5 minutes)
2. ✅ Update .env file (1 minute)
3. ✅ Start application and test

**No DBA needed. No waiting. Start now!** 🚀

---

**Questions?** Check `PERSONAL_SCHEMA_README.md` for detailed instructions.
