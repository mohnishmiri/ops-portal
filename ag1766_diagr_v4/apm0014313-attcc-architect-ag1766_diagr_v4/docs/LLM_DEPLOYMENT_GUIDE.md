# LLM Provider Integration Deployment Guide

**Version:** 1.0  
**Last Updated:** 2026-09-18  
**Status:** Production-ready (PAI-7 complete)

---

## Overview

This guide documents the deployment, configuration, and operational procedures for the LLM provider integration (PAI-1 through PAI-7). The integration supports provider-neutral AI-assisted candidate mapping with strict security gates, audit lineage, and policy enforcement.

---

## 1. Architecture Summary

### Components
- **Provider-neutral completion boundary** (`StructuredCompletionClient`)
- **Candidate mapping service** (bounded fragments, local validation)
- **AI mapping run persistence** (append-only lineage)
- **Capability-gated web routes** (`AI_MAPPING_RUN` capability)
- **Provider adapters** (OpenAI-compatible, mock, disabled)

### Security Invariants
✅ Every AI-produced value remains `PROPOSED` until reviewer accepts  
✅ HTTPS mandatory (HTTP only for loopback test servers)  
✅ Tokens never enter logs, exceptions, or database  
✅ No provider receives requests until all gates pass  
✅ Application never accepts provider config from browser/evidence/database  

---

## 2. Configuration

### 2.1 Helm Values Structure

```yaml
llm:
  enabled: false                    # Master enable flag
  provider: mock                    # mock | openai_compatible | anthropic | bedrock
  profile: disabled                 # Deployment-approved profile label
  outboundEnabled: false            # Outbound call gate (independent of enabled)
  baseUrl: ""                       # Provider endpoint (HTTPS required)
  model: ""                         # Provider model identifier
  authMode: bearer_token            # bearer_token | workload_identity
  allowedClassifications: "SYNTHETIC"  # Comma-separated (SYNTHETIC, CLIENT, etc.)
  connectTimeoutSeconds: 10
  readTimeoutSeconds: 60
  maxAttempts: 3
  maxResponseBytes: 10485760        # 10 MB
  maxFragmentChars: 12000
  maxRequestsPerImport: 20
```

### 2.2 Environment-Specific Profiles

#### Local Development
```yaml
llm:
  enabled: false
  provider: mock
  profile: local-dev
  outboundEnabled: false
```

#### Shared Test (Synthetic Only)
```yaml
llm:
  enabled: true
  provider: openai_compatible
  profile: shared-test-synthetic
  outboundEnabled: true
  baseUrl: "https://llm-gateway.test.att.com"
  model: "approved-test-model"
  authMode: bearer_token
  allowedClassifications: "SYNTHETIC"
```

#### Production (Disabled Until Approved)
```yaml
llm:
  enabled: false
  provider: mock
  profile: production-disabled
  outboundEnabled: false
```

### 2.3 Secret Manager Integration

**Required Secret:** `AWS_OUTPOST_LLM_API_TOKEN`

#### Azure Key Vault (Recommended)
```yaml
azureKeyVaultSecrets:
  enabled: true
  vaultName: "attcc-prod-kv"
  items:
    - secretName: llm-api-token
      envName: AWS_OUTPOST_LLM_API_TOKEN
```

#### Kubernetes Secret (Alternative)
```bash
kubectl create secret generic migration-intake-llm-secrets \
  --from-literal=AWS_OUTPOST_LLM_API_TOKEN='<token-value>' \
  --namespace=<namespace>
```

```yaml
extraEnvFrom:
  - secretRef:
      name: migration-intake-llm-secrets
```

---

## 3. Deployment Verification Checklist

### Pre-Deployment
- [ ] Review and approve LLM provider profile configuration
- [ ] Verify `AWS_OUTPOST_LLM_API_TOKEN` is injected via secret manager
- [ ] Confirm `allowedClassifications` matches data governance policy
- [ ] Validate `baseUrl` is HTTPS and approved endpoint
- [ ] Ensure `outboundEnabled=false` unless explicitly approved

### Post-Deployment
- [ ] Verify pod starts successfully (`kubectl get pods`)
- [ ] Check migration `0017_ai_mapping_runs` applied (`kubectl logs <pod> -c migrate`)
- [ ] Confirm `/health/ready` returns 200
- [ ] Validate LLM configuration in logs (provider/profile redacted, no tokens)
- [ ] Test mock provider end-to-end (if `provider=mock`)
- [ ] Test disabled profile rejection (if `outboundEnabled=false`)

### Smoke Test (Mock Provider)
```bash
# 1. Navigate to evidence list page
curl -X GET https://<host>/applications/<app_id>/intakes/<intake_id>/sources \
  -H "Cookie: session=<session>"

# 2. Submit AI mapping request
curl -X POST https://<host>/applications/<app_id>/intakes/<intake_id>/ai-mapping/run \
  -H "Cookie: session=<session>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "_csrf_token=<token>&source_fragment=Linux+host&source_locator=Manual:AI/Row:1&source_type=manual_text"

# 3. Verify candidate staged
# Check database: SELECT * FROM candidates WHERE origin LIKE 'AI:%' ORDER BY created_at DESC LIMIT 1;
# Check AI run: SELECT * FROM ai_mapping_runs ORDER BY created_at DESC LIMIT 1;
```

---

## 4. Provider Connectivity Troubleshooting

### Issue: `OutboundAIDisabledError`
**Symptoms:** AI mapping fails with "AI mapping is disabled by profile policy"

**Root Causes:**
1. `llm.enabled=false` in Helm values
2. `llm.outboundEnabled=false` in Helm values
3. `llm.provider=mock` (mock cannot perform outbound calls)

**Resolution:**
```yaml
llm:
  enabled: true
  outboundEnabled: true
  provider: openai_compatible  # Not mock
```

### Issue: `ProviderAuthError`
**Symptoms:** AI mapping fails with "Provider authentication failed (HTTP 401/403)"

**Root Causes:**
1. `AWS_OUTPOST_LLM_API_TOKEN` not injected
2. Token expired or invalid
3. Token does not have permission for endpoint

**Resolution:**
1. Verify secret exists: `kubectl get secret migration-intake-llm-secrets -o yaml`
2. Check pod env: `kubectl exec <pod> -- env | grep LLM_API_TOKEN` (should be `<secret>`)
3. Rotate token in secret manager and restart pod

### Issue: `ProviderTransportError`
**Symptoms:** AI mapping fails with "Transport failure" or "timeout"

**Root Causes:**
1. Network policy blocking egress to LLM endpoint
2. Endpoint URL incorrect or unreachable
3. Timeout too short for provider latency

**Resolution:**
1. Verify network policy allows egress: `kubectl get networkpolicy`
2. Test connectivity from pod: `kubectl exec <pod> -- curl -I <baseUrl>`
3. Increase timeouts in Helm values:
```yaml
llm:
  connectTimeoutSeconds: 30
  readTimeoutSeconds: 120
```

### Issue: Classification Blocked
**Symptoms:** AI mapping fails with "Request classification 'CLIENT' is not allowed by policy"

**Root Causes:**
1. `allowedClassifications` does not include requested classification
2. Evidence classification mismatch

**Resolution:**
```yaml
llm:
  allowedClassifications: "SYNTHETIC,CLIENT"  # Add CLIENT if approved
```

---

## 5. Monitoring and Alerting

### Key Metrics

#### Application Metrics
- `ai_mapping_runs.status=COMPLETED` (success rate)
- `ai_mapping_runs.status=FAILED` (failure rate)
- `ai_mapping_runs.attempt_count` (retry distribution)
- `ai_mapping_runs.candidate_count` (mapping yield)

#### Provider Metrics
- Response latency buckets (`<=250ms`, `<=1s`, `>1s`)
- HTTP status codes (401, 429, 500+)
- Retry exhaustion rate

### Recommended Alerts

#### Critical
```yaml
- alert: LLMProviderAuthFailure
  expr: rate(ai_mapping_runs{failure_category="AUTH"}[5m]) > 0.1
  severity: critical
  description: "LLM provider authentication failing (check token rotation)"

- alert: LLMProviderUnavailable
  expr: rate(ai_mapping_runs{failure_category="TRANSPORT"}[5m]) > 0.5
  severity: critical
  description: "LLM provider unreachable (check network/endpoint)"
```

#### Warning
```yaml
- alert: LLMHighRetryRate
  expr: avg(ai_mapping_runs.attempt_count) > 2
  severity: warning
  description: "LLM requests requiring multiple retries (check provider latency)"

- alert: LLMLowMappingYield
  expr: avg(ai_mapping_runs.candidate_count) < 0.5
  severity: warning
  description: "LLM producing few candidates (check prompt template)"
```

### Log Queries

#### Failed AI Mapping Runs
```sql
SELECT id, provider_id, profile_id, status, failure_category, failure_detail_redacted, created_at
FROM ai_mapping_runs
WHERE status = 'FAILED'
ORDER BY created_at DESC
LIMIT 50;
```

#### Candidate Acceptance Rate
```sql
SELECT 
  COUNT(*) FILTER (WHERE state = 'PROPOSED') AS proposed,
  COUNT(*) FILTER (WHERE state = 'ACCEPTED') AS accepted,
  COUNT(*) FILTER (WHERE state = 'REJECTED') AS rejected
FROM candidates
WHERE origin LIKE 'AI:%'
  AND created_at > NOW() - INTERVAL '7 days';
```

---

## 6. Operational Runbook

### 6.1 Enable LLM Provider (First Time)

**Prerequisites:**
- [ ] Architecture/security/data-governance approval obtained
- [ ] Provider endpoint approved and accessible
- [ ] API token provisioned in secret manager
- [ ] Data classification policy documented

**Steps:**
1. Update Helm values for target environment:
```yaml
llm:
  enabled: true
  provider: openai_compatible
  profile: "<approved-profile-name>"
  outboundEnabled: true
  baseUrl: "https://<approved-endpoint>"
  model: "<approved-model>"
  authMode: bearer_token
  allowedClassifications: "SYNTHETIC"  # Start with SYNTHETIC only
```

2. Deploy via Helm:
```bash
helm upgrade migration-intake ./helm \
  --namespace <namespace> \
  --values helm/envs/<env>/values.yaml \
  --wait
```

3. Verify deployment (see checklist above)

4. Perform smoke test with synthetic fragment

5. Monitor for 24 hours before enabling additional classifications

### 6.2 Rotate API Token

**Steps:**
1. Generate new token in provider portal
2. Update secret in Azure Key Vault or Kubernetes:
```bash
kubectl create secret generic migration-intake-llm-secrets \
  --from-literal=AWS_OUTPOST_LLM_API_TOKEN='<new-token>' \
  --namespace=<namespace> \
  --dry-run=client -o yaml | kubectl apply -f -
```
3. Restart pods to pick up new secret:
```bash
kubectl rollout restart deployment/migration-intake -n <namespace>
```
4. Verify authentication succeeds

### 6.3 Disable LLM Provider (Emergency)

**Steps:**
1. Update Helm values:
```yaml
llm:
  enabled: false
  outboundEnabled: false
```
2. Deploy immediately:
```bash
helm upgrade migration-intake ./helm \
  --namespace <namespace> \
  --values helm/envs/<env>/values.yaml \
  --wait
```
3. Verify no outbound calls occur (check logs for `OutboundAIDisabledError`)

### 6.4 Add New Provider Adapter

**Prerequisites:**
- [ ] Provider adapter implemented and tested (PAI-3 pattern)
- [ ] Provider registered in `provider_registry.py`
- [ ] Security review completed
- [ ] Integration tests passing

**Steps:**
1. Deploy new adapter code
2. Update Helm values:
```yaml
llm:
  provider: anthropic  # or bedrock, azure_openai, etc.
  authMode: <provider-specific>
```
3. Follow "Enable LLM Provider" runbook

---

## 7. Security Considerations

### Token Handling
- ✅ Tokens injected via secret manager (never in values.yaml or configmap)
- ✅ Tokens never logged, persisted, or included in exception messages
- ✅ Rotate tokens every 90 days minimum

### Network Security
- ✅ HTTPS required for all provider endpoints
- ✅ HTTP only allowed for `127.0.0.1` loopback test servers
- ✅ Network policies restrict egress to approved endpoints

### Data Classification
- ✅ Start with `SYNTHETIC` classification only
- ✅ Require explicit approval before enabling `CLIENT` classification
- ✅ Never send credentials, PII, or secrets to provider

### Audit Trail
- ✅ Every AI mapping run recorded in `ai_mapping_runs` table
- ✅ Request/response hashes stored for lineage
- ✅ Provider/profile/model metadata captured
- ✅ All AI-produced candidates remain `PROPOSED` until reviewer accepts

---

## 8. Known Limitations

1. **Single fragment per request** - No batch optimization yet
2. **SYNTHETIC classification only** - CLIENT evidence blocked until approval
3. **No UI for run history** - Query `ai_mapping_runs` table directly
4. **Simple JSON parsing** - No schema validation beyond grounding checks
5. **Provider-agnostic retries** - No provider-specific backoff strategies

---

## 9. Future Enhancements

- [ ] Anthropic adapter implementation
- [ ] Bedrock adapter implementation
- [ ] Azure OpenAI adapter
- [ ] Batch mapping optimization
- [ ] AI mapping run history UI
- [ ] Enhanced prompt templates (v2.0+)
- [ ] Provider-specific retry strategies
- [ ] Real-time mapping progress indicators

---

## 10. Support and Escalation

### Tier 1: Application Logs
```bash
kubectl logs -f deployment/migration-intake -n <namespace> | grep -i "llm\|ai_mapping"
```

### Tier 2: Database Inspection
```sql
-- Recent AI mapping runs
SELECT * FROM ai_mapping_runs ORDER BY created_at DESC LIMIT 10;

-- Failed runs with details
SELECT id, provider_id, failure_category, failure_detail_redacted, created_at
FROM ai_mapping_runs
WHERE status = 'FAILED'
ORDER BY created_at DESC;
```

### Tier 3: Provider Support
- OpenAI-compatible: Check provider documentation for rate limits, auth, endpoints
- Anthropic: Contact Anthropic support with `provider_request_id`
- Bedrock: Check AWS CloudWatch logs for invocation failures

### Escalation Path
1. **Application Team** - Configuration, deployment, application errors
2. **Security Team** - Token rotation, network policy, data classification
3. **Provider Support** - Provider-specific transport/auth/rate-limit issues

---

## Appendix A: Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_OUTPOST_LLM_ENABLED` | Yes | `false` | Master enable flag |
| `AWS_OUTPOST_LLM_PROVIDER` | Yes | `mock` | Provider ID (`mock`, `openai_compatible`, `anthropic`, `bedrock`) |
| `AWS_OUTPOST_LLM_PROFILE` | Yes | `disabled` | Deployment-approved profile label |
| `AWS_OUTPOST_LLM_OUTBOUND_ENABLED` | Yes | `false` | Outbound call gate |
| `AWS_OUTPOST_LLM_BASE_URL` | Conditional | - | Provider endpoint (required if outbound enabled) |
| `AWS_OUTPOST_LLM_MODEL` | Conditional | - | Model identifier (required if outbound enabled) |
| `AWS_OUTPOST_LLM_AUTH_MODE` | Yes | `bearer_token` | Auth mode (`bearer_token`, `workload_identity`) |
| `AWS_OUTPOST_LLM_API_TOKEN` | Conditional | - | Bearer token (required if `authMode=bearer_token`) |
| `AWS_OUTPOST_LLM_ALLOWED_CLASSIFICATIONS` | Yes | `SYNTHETIC` | Comma-separated classification list |
| `AWS_OUTPOST_LLM_CONNECT_TIMEOUT_SECONDS` | No | `10` | Connection timeout |
| `AWS_OUTPOST_LLM_READ_TIMEOUT_SECONDS` | No | `60` | Read timeout |
| `AWS_OUTPOST_LLM_MAX_ATTEMPTS` | No | `3` | Max retry attempts |
| `AWS_OUTPOST_LLM_MAX_RESPONSE_BYTES` | No | `10485760` | Max response size (10 MB) |
| `AWS_OUTPOST_LLM_MAX_FRAGMENT_CHARS` | No | `12000` | Max fragment size |
| `AWS_OUTPOST_LLM_MAX_REQUESTS_PER_IMPORT` | No | `20` | Max requests per import run |

---

**Document Version:** 1.0  
**Maintained By:** Migration Intake Team  
**Last Reviewed:** 2026-09-18
