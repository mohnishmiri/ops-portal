# LLM Local Development Setup Guide

**Target Endpoint:** `http://zld02251.vci.att.com:8000`  
**Model:** `gpt-4o-mini`  
**Last Updated:** 2026-09-18

---

## ⚠️ Critical Configuration Notes

### 1. **Base URL Must NOT Include `/v1`**

The OpenAI-compatible adapter automatically appends `/v1/chat/completions` to the base URL.

❌ **WRONG:**
```bash
AWS_OUTPOST_LLM_BASE_URL=http://zld02251.vci.att.com:8000/v1
# Results in: http://zld02251.vci.att.com:8000/v1/v1/chat/completions
```

✅ **CORRECT:**
```bash
AWS_OUTPOST_LLM_BASE_URL=http://zld02251.vci.att.com:8000
# Results in: http://zld02251.vci.att.com:8000/v1/chat/completions
```

### 2. **HTTP is Blocked by Security Gates**

The application enforces HTTPS for all non-loopback endpoints. Since `zld02251.vci.att.com` is not a loopback address (`127.0.0.1` or `localhost`), HTTP will be rejected with:

```
OutboundAIDisabledError: HTTPS is required for provider base URL
```

**Solutions:**

#### Option A: Use HTTPS (Recommended)
If the endpoint supports HTTPS:
```bash
AWS_OUTPOST_LLM_BASE_URL=https://zld02251.vci.att.com:8000
```

#### Option B: Temporarily Bypass for Local Dev (Not Recommended)
The `allow_http_for_testing` parameter exists but is **not exposed** via environment variables for security reasons. To enable HTTP for local development:

1. **Modify the provider registry** (temporary local change, do not commit):

```python
# src/migration_intake/ai/provider_registry.py (line 81-84)
registry.register(
    "openai_compatible",
    lambda settings: OpenAICompatibleCompletionClient(
        settings,
        allow_http_for_testing=True  # ADD THIS LINE FOR LOCAL DEV ONLY
    ),
)
```

2. **Revert this change** before committing any code.

#### Option C: Use SSH Tunnel to Localhost
Create an SSH tunnel to make the endpoint appear as localhost:
```bash
ssh -L 8000:zld02251.vci.att.com:8000 your-jump-host
```

Then configure:
```bash
AWS_OUTPOST_LLM_BASE_URL=http://localhost:8000
```

---

## Configuration for `gpt-4o-mini`

### Complete `.env` Configuration

Create a `.env` file in the project root with the following content:

```bash
# ============================================================================
# Database (SQLite for local dev)
# ============================================================================
AWS_OUTPOST_DATABASE_URL=sqlite:///./local.db

# ============================================================================
# Application Settings
# ============================================================================
AWS_OUTPOST_APP_ENV=local
AWS_OUTPOST_EVIDENCE_ROOT=./evidence
AWS_OUTPOST_ACTOR_ID=00000000-0000-0000-0000-000000000001
AWS_OUTPOST_ACTOR_DISPLAY_NAME=Local Developer
AWS_OUTPOST_CSRF_SECRET=local-dev-csrf-secret-minimum-32-characters-long-12345

# ============================================================================
# LLM Provider Configuration - OpenAI-Compatible (zld02251.vci.att.com)
# ============================================================================

# Enable LLM functionality
AWS_OUTPOST_LLM_ENABLED=true

# Provider type (openai_compatible for OpenAI-compatible endpoints)
AWS_OUTPOST_LLM_PROVIDER=openai_compatible

# Profile identifier (for audit/logging)
AWS_OUTPOST_LLM_PROFILE=local-zld02251-gpt4o-mini

# Enable outbound calls
AWS_OUTPOST_LLM_OUTBOUND_ENABLED=true

# Base URL WITHOUT /v1 suffix
# IMPORTANT: Use HTTPS if available, or see HTTP bypass options above
AWS_OUTPOST_LLM_BASE_URL=http://zld02251.vci.att.com:8000

# Model identifier
AWS_OUTPOST_LLM_MODEL=gpt-4o-mini

# Authentication mode
AWS_OUTPOST_LLM_AUTH_MODE=bearer_token

# API Token (replace with your actual token)
AWS_OUTPOST_LLM_API_TOKEN=your-api-token-here

# Data classification policy (start with SYNTHETIC only)
AWS_OUTPOST_LLM_ALLOWED_CLASSIFICATIONS=SYNTHETIC

# Timeouts and limits
AWS_OUTPOST_LLM_CONNECT_TIMEOUT_SECONDS=10
AWS_OUTPOST_LLM_READ_TIMEOUT_SECONDS=60
AWS_OUTPOST_LLM_MAX_ATTEMPTS=3
AWS_OUTPOST_LLM_MAX_RESPONSE_BYTES=10485760
AWS_OUTPOST_LLM_MAX_FRAGMENT_CHARS=12000
AWS_OUTPOST_LLM_MAX_REQUESTS_PER_IMPORT=20

# ============================================================================
# Logging
# ============================================================================
LOG_LEVEL=DEBUG
LOG_FORMAT=human
```

---

## Variable Reference

| Variable | Value for `gpt-4o-mini` | Description |
|----------|-------------------------|-------------|
| `AWS_OUTPOST_LLM_ENABLED` | `true` | Master enable flag |
| `AWS_OUTPOST_LLM_PROVIDER` | `openai_compatible` | Provider type |
| `AWS_OUTPOST_LLM_PROFILE` | `local-zld02251-gpt4o-mini` | Profile label for audit |
| `AWS_OUTPOST_LLM_OUTBOUND_ENABLED` | `true` | Allow outbound calls |
| `AWS_OUTPOST_LLM_BASE_URL` | `http://zld02251.vci.att.com:8000` | **Without `/v1`** |
| `AWS_OUTPOST_LLM_MODEL` | `gpt-4o-mini` | Model identifier |
| `AWS_OUTPOST_LLM_AUTH_MODE` | `bearer_token` | Auth method |
| `AWS_OUTPOST_LLM_API_TOKEN` | `<your-token>` | Bearer token |
| `AWS_OUTPOST_LLM_ALLOWED_CLASSIFICATIONS` | `SYNTHETIC` | Data classification |
| `AWS_OUTPOST_LLM_CONNECT_TIMEOUT_SECONDS` | `10` | Connection timeout |
| `AWS_OUTPOST_LLM_READ_TIMEOUT_SECONDS` | `60` | Read timeout |
| `AWS_OUTPOST_LLM_MAX_ATTEMPTS` | `3` | Max retry attempts |
| `AWS_OUTPOST_LLM_MAX_RESPONSE_BYTES` | `10485760` | Max response size (10 MB) |
| `AWS_OUTPOST_LLM_MAX_FRAGMENT_CHARS` | `12000` | Max fragment size |
| `AWS_OUTPOST_LLM_MAX_REQUESTS_PER_IMPORT` | `20` | Max requests per import |

---

## Verification Steps

### 1. Start the Application
```bash
python -m uvicorn migration_intake.main:app --reload --port 8000
```

### 2. Check Startup Logs
Look for LLM configuration in startup logs:
```
INFO: LLM provider: openai_compatible
INFO: LLM profile: local-zld02251-gpt4o-mini
INFO: LLM outbound: enabled
```

**⚠️ If you see HTTP rejection:**
```
OutboundAIDisabledError: HTTPS is required for provider base URL
```
→ See "HTTP is Blocked" section above for solutions.

### 3. Test AI Mapping Endpoint

Navigate to:
```
http://localhost:8000/applications/<app_id>/intakes/<intake_id>/sources
```

Click the "AI synthetic mapping" button and submit a test fragment:
```
Fragment: "Linux host with 8 GB RAM"
```

### 4. Verify Request
Check logs for outbound request:
```
DEBUG: POST http://zld02251.vci.att.com:8000/v1/chat/completions
DEBUG: Model: gpt-4o-mini
DEBUG: Classification: SYNTHETIC
```

### 5. Check Database
```sql
SELECT * FROM ai_mapping_runs ORDER BY created_at DESC LIMIT 1;
SELECT * FROM candidates WHERE origin LIKE 'AI:%' ORDER BY created_at DESC LIMIT 5;
```

---

## Troubleshooting

### Issue: "HTTPS is required for provider base URL"
**Cause:** HTTP is blocked for non-loopback endpoints.

**Solutions:**
1. Use HTTPS if endpoint supports it
2. Use SSH tunnel to localhost (see Option C above)
3. Temporarily modify provider registry (see Option B above, **do not commit**)

### Issue: "404 Not Found" from Provider
**Cause:** Base URL includes `/v1`, resulting in `/v1/v1/chat/completions`.

**Solution:** Remove `/v1` from `AWS_OUTPOST_LLM_BASE_URL`:
```bash
# WRONG
AWS_OUTPOST_LLM_BASE_URL=http://zld02251.vci.att.com:8000/v1

# CORRECT
AWS_OUTPOST_LLM_BASE_URL=http://zld02251.vci.att.com:8000
```

### Issue: "Provider authentication failed (HTTP 401)"
**Cause:** Invalid or missing API token.

**Solution:** Verify token is correct:
```bash
curl -H "Authorization: Bearer your-api-token-here" \
  http://zld02251.vci.att.com:8000/v1/models
```

### Issue: "Request classification 'CLIENT' is not allowed by policy"
**Cause:** Trying to use CLIENT evidence without approval.

**Solution:** Use SYNTHETIC classification only for local dev:
```bash
AWS_OUTPOST_LLM_ALLOWED_CLASSIFICATIONS=SYNTHETIC
```

---

## Security Reminders

1. **Never commit `.env` file** - It contains your API token
2. **Never commit HTTP bypass** - Revert `allow_http_for_testing=True` before committing
3. **Start with SYNTHETIC only** - Don't enable CLIENT classification without approval
4. **Rotate tokens regularly** - API tokens should be rotated every 90 days
5. **Use HTTPS in production** - HTTP is only for local development

---

## Alternative: Mock Provider (No Network Calls)

If you want to test the UI without making real API calls:

```bash
AWS_OUTPOST_LLM_ENABLED=false
AWS_OUTPOST_LLM_PROVIDER=mock
AWS_OUTPOST_LLM_PROFILE=local-mock
AWS_OUTPOST_LLM_OUTBOUND_ENABLED=false
```

The mock provider returns deterministic responses:
- Always maps to `os_type=LINUX`
- No network calls
- No API token required

---

## Next Steps

1. **Configure `.env`** with values above
2. **Choose HTTP bypass method** (HTTPS, SSH tunnel, or temporary registry modification)
3. **Start application** and verify startup logs
4. **Test AI mapping** with synthetic fragment
5. **Check database** for mapping run and candidates
6. **Revert any local changes** before committing

---

**Document Version:** 1.0  
**Last Updated:** 2026-09-18  
**Maintained By:** Migration Intake Team
