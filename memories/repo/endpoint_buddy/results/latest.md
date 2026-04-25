# Compliance Page Endpoint Test Results

Timestamp: 2026-03-14T18:01:35Z
Environment: dev
Frontend: http://127.0.0.1:5177/compliance
Backend: http://127.0.0.1:8002

| Name | Method | Status | Result | Notes |
| --- | --- | --- | --- | --- |
| Compliance page HTML | GET | 200 | PASS | Request must use text/html and 127.0.0.1 |
| Backend health | GET | 200 | PASS | /healthz healthy |
| Compliance dashboard | GET | 200 | PASS | |
| Synapse drift summary | GET | 200 | PASS | Slow: 8.1s |
| Synapse drift list | GET | 200 | PASS | 3.5s |
| Synapse workspaces | GET | 200 | PASS | 5.3s |
| Checksum runs | GET | 200 | PASS | |
| Checksum metrics | GET | 200 | PASS | |
| Checksum results | GET | 200 | PASS | 2.6s |
| AKS checksum runs | GET | 200 | PASS | |
| AKS checksum metrics | GET | 200 | PASS | |
| AKS checksum results | GET | 200 | PASS | |
| Cached AKS clusters | GET | 200 | PASS | |
| Checksum schedules list | GET | 200 | PASS | |
| Workspace drift summary | GET | 200 | PASS | |
| Workspace drift list | GET | 200 | PASS | |
| Workspace checksum comparison | GET | 200 | PASS | |
| AKS namespaces | GET | 200 | PASS | Slow: 6.1s |
| Checksum schedule detail | GET | 200 | PASS | Fixed: _normalize_schedule_id() int conversion |
| Export Excel | GET | 200 | PASS | Fixed: 4 sheets, 96425 rows, ~136s, all data correct |
| Calculate compliance score | POST | 200 | PASS | |
| Run checksum verification | POST | 200 | PASS | Heavy: 59.8s |
| Collect Synapse checksums | POST | 200 | PASS | Heavy: 57.3s |
| AKS checksum verification | POST | 200 | PASS | 6.3s, returned 28 failures but endpoint completed |
| Checksum download for Synapse run | GET | 200 | PASS | CSV returned |
| Checksum download for AKS run | GET | 404 | FAIL | No results found for the latest AKS run ID |
