# ZeroCode Cloud — API foundation

ZeroCode Cloud is the remote AI gateway and control plane for ZeroCode clients. The Python agent continues to own local files, shell commands, Git, tests and tool permissions. Cloud receives only the conversation/context explicitly sent for model inference.

## Included in this first milestone

- FastAPI API with health endpoints.
- Account registration (configurable), login, short-lived JWT access tokens and rotating device refresh tokens.
- Device inventory and remote revocation.
- Admin-only provider/model catalog management.
- Provider API keys encrypted at rest with Fernet; they are never returned by API responses.
- Per-task routing policies, fallback across configured OpenAI-compatible provider endpoints, and streamed chat completions.
- Remote client config, emergency maintenance switch, feature flags, usage events and administrative audit records.
- Server-enforced per-account and global request-rate/concurrency limits.
- Per-request message/payload/output limits and a cap on active device sessions per account.
- Admin endpoints to inspect service health and users, suspend accounts, revoke devices and tune operational guardrails.
- PostgreSQL and SQLite development support, Docker Compose.

The administration API is available now; a browser-based control panel is still a separate follow-up. The server currently supports OpenAI-compatible upstream APIs and does not execute user code remotely.

## Local development

```bash
cd cloud
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Generate two independent secrets:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Put them in `.env`. Then start PostgreSQL and the API:

```bash
docker compose up --build
```

In development, docs are available at `http://localhost:8000/docs`.

## First administrator

Set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` before the first server start. If that email does not exist, the service creates it with the admin role. Remove the bootstrap password from the environment after initial setup. Never use the sample values in production.

Public signup is disabled by default (`ALLOW_PUBLIC_SIGNUP=false`). Provision the first administrator through the bootstrap environment variables. Only enable signup temporarily in a controlled development environment; do not open it to the public until email verification, abuse protection and account recovery are ready.

## Connect a ZeroCode client

```bash
zerocode cloud login --url https://YOUR-CLOUD-HOST
zerocode cloud status
```

To switch between the managed gateway and direct local/BYOK providers:

```bash
zerocode cloud use cloud
zerocode cloud use local
zerocode cloud logout
```

The access/refresh tokens are stored in the user's ZeroCode configuration directory in `cloud.json` with restrictive file permissions (0600 on POSIX). A device refresh token is rotated on each refresh. On Windows, protect the user's profile with the operating-system account; OS-backed credential storage is a future hardening step.

## API surface

- `GET /v1/health/live`, `GET /v1/health/ready`
- `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/refresh`, `POST /v1/auth/logout`
- `GET /v1/auth/me`, `GET /v1/auth/devices`, `DELETE /v1/auth/devices/{id}`
- `GET /v1/client/config`
- `POST /v1/chat/completions` (OpenAI-compatible request body and SSE streaming)
- Admin: `GET/POST /v1/admin/providers`, `PATCH /v1/admin/providers/{id}`
- Admin: `GET/POST /v1/admin/models`, `PATCH /v1/admin/models/{id}`
- Admin: `GET/PUT /v1/admin/routing`, `PATCH /v1/admin/client-config`
- Admin: `GET /v1/admin/overview`, `GET /v1/admin/users`, `PATCH /v1/admin/users/{id}`
- Admin: `POST /v1/admin/users/{id}/devices/{device_id}/revoke`
- Admin: `GET/PATCH /v1/admin/guardrails`
- Admin: `GET /v1/admin/usage/summary`, `GET /v1/admin/usage/recent`, `GET /v1/admin/audit-logs`

## Operational guardrails

The default limits are intentionally conservative and are enforced by the Cloud API, not by the Desktop or CLI interface:

| Control | Default |
| --- | ---: |
| Requests per account | 12 per minute |
| Concurrent requests per account | 2 |
| Requests across the service | 240 per minute |
| Concurrent requests across the service | 40 |
| Output generation | 8,192 tokens per request |
| Prompt size | 120,000 serialized characters |
| Messages per request | 100 |
| Active device sessions per account | 5 |

An administrator can read or update these settings through `GET/PATCH /v1/admin/guardrails`. When an account is suspended, all its device sessions are revoked and existing access tokens stop authenticating. A new login is required after an account is re-enabled. When the device ceiling is reached, the oldest active session is revoked automatically.

The `maintenance_mode` setting in `PATCH /v1/admin/client-config` blocks new AI requests service-wide. Individual providers and model routes can also be disabled without changing client installations.

Request admission is recorded in PostgreSQL so limits are shared across Cloud API workers. Short-lived request leases expire automatically after an interrupted process; completed and expired lease records are cleaned up on subsequent admissions.

## Configure a model route

1. Sign in with the bootstrap administrator account using `/v1/auth/login`.
2. Create a provider, for example Kilo Gateway with base URL `https://ai-gateway.kilo.ai/api/v1`.
3. Create one or more model aliases with `/v1/admin/models`.
4. Assign ordered aliases to a task route, for example `PUT /v1/admin/routing/coding`.
5. Connect ZeroCode Desktop or CLI with `zerocode cloud login`.

Provider credentials remain on the server. The client sends OpenAI-compatible requests to ZeroCode Cloud and keeps executing requested tools locally. If an upstream request fails before a stream begins, the gateway tries the next route. It never switches models after response bytes have already been sent.

## Deployment and production gate

This remains a pre-release service. Before exposing it broadly, add admin MFA, secrets rotation, a browser-based control panel, explicit data retention/deletion rules, backups and restore drills, monitoring/alerting, and load/security tests. Failed sign-in attempts are now rate-limited per normalized account email using persistent database state (8 failures per 15-minute window, followed by a 15-minute block). Run Alembic migrations before production data is stored; do not rely on development-only automatic schema creation.

A free hosting tier can sleep, restart, or lose ephemeral files. Use durable managed PostgreSQL storage, backups and an always-on service before relying on the Cloud control plane for active users.
