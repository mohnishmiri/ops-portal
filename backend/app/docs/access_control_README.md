# Access Control & Subscription Filtering — Implementation Guide

## Overview
This document describes the implementation of granular access control (RBAC/ABAC) and subscription-based data filtering for the Azure Ops Portal backend.

## Models
- **Resource**: Represents a module or page.
- **Permission**: Grants a user or role access to a resource with a specific permission type (view/edit).

## Middleware
- **AccessControlMiddleware**: Enforces per-request resource access based on user/role permissions.
- **SubscriptionFilterMiddleware**: Ensures all data access is filtered by the user's allowed subscriptions.

## Admin Endpoints
- `/permissions/resources` — Create/list resources (modules/pages)
- `/permissions/permissions` — Create/list permissions (user/role-resource mapping)

## Extending the System
1. Register new modules/pages as resources via the admin endpoint.
2. Assign permissions to users/roles for those resources.
3. Middleware will enforce access automatically.

## Migration
- Run Alembic migrations to create `resources` and `permissions` tables.
- Register existing modules/pages as resources.
- Assign initial permissions for admin roles.

## Testing
- Add unit/integration tests for permission checks and subscription filtering.

## Example Usage
- To add a new page/module, POST to `/permissions/resources`.
- To grant a user view access, POST to `/permissions/permissions` with subject_type `user` and permission_type `view`.

---
For questions, see the code comments in `middleware/access_control.py` and `api/v1/endpoints/permissions.py`.
