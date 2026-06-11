# Access Control & Subscription Scoping — Implementation Guide

## Overview

The portal enforces access in layers:

1. **Entra App Roles** → `UserContext` (`ADMIN` / `WRITE` / `READ`)
2. **Permission records** (optional page/module grants in DB)
3. **Subscription scope** (admin monitored set + per-user selection + optional RBAC allow-list)

## Models

| Model | Purpose |
|-------|---------|
| `Resource` | Module or page identifier for fine-grained permissions |
| `Permission` | Grants a user or role `view` / `edit` on a resource |
| `AdminSubscription` | Admin-managed subscription registry (`enabled`, `monitored`, `environment`) |
| `UserSubscriptionPreference` | Per-user `selected_subscription_ids` (JSON), keyed by `user_id` |

## Subscription scoping (not middleware)

Read-path scoping is implemented via a **router dependency**, not `SubscriptionFilterMiddleware`:

| Component | Location | Role |
|-----------|----------|------|
| `get_monitored_subscription_ids()` | `app/core/subscription_resolver.py` | Admin ceiling; used by sync jobs |
| `bind_subscription_scope` | `app/core/subscription_scope.py` | FastAPI dependency on `/api/v1` router |
| `get_scoped_subscription_ids()` | `app/core/subscription_scope.py` | Called by services during HTTP reads |
| `resolve_effective_subscription_ids()` | `app/core/subscription_scope.py` | Shared resolver for auth preference APIs |
| `UserPreferenceService` | `app/services/user_preference_service.py` | Persist/load per-user picker state |

Effective scope for a request:

```
monitored ∩ allowed_subscriptions (if set) ∩ subscription_ids query param (if set)
```

Empty `selected_subscription_ids` in the DB or omitted query param means **all monitored**.

## Auth scope endpoints

- `GET /api/v1/auth/available-subscriptions`
- `GET /api/v1/auth/subscription-scope`
- `PUT /api/v1/auth/subscription-scope`

## Admin endpoints

- `/api/v1/admin/subscriptions` — CRUD, toggle `enabled` / `monitored`, sync from Azure
- `/api/v1/permissions/*` — resource and permission management

## Cost cleanup authorization

`POST /api/v1/optimize/cleanup/*` requires portal `ADMIN` plus Azure RBAC delete rights on the target subscription. See `app/api/v1/endpoints/optimization.py`.

## Extending the system

1. Register new modules/pages as `Resource` rows.
2. Assign `Permission` grants to roles or users.
3. For subscription-scoped data, call `get_scoped_subscription_ids()` in the service layer — do not filter only in the frontend.
4. Background jobs that must process all monitored subs should call `get_monitored_subscription_ids()` directly.

## Testing

- `tests/test_subscription_scope.py` — resolver and context binding
- `tests/test_infra_alert_subscription_scope.py` — service read filtering
- `tests/test_api.py` — cleanup endpoint role and validation checks
