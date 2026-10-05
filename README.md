# Konnective Tissue — AI Auditor Agent
![CI](https://github.com/SaurabhIVYhuts/Auditor/actions/workflows/ci.yml/badge.svg)

A continuous-audit assistant for hospitals.
It checks transactions against configurable rules and statistical baselines, turns exceptions into risk-scored audit cases,
and supports auditors through investigation, evidence, findings, corrective actions and reports.

> **AI assists; authorised humans decide.**

## Folder structure

```
shared/                  placeholders for shared platform services (auth/RBAC, audit log, documents, notifications, AI gateway)
agents/                  container for agents
agents/audit/            the Auditor Agent
agents/audit/api/        FastAPI routers (thin: validate input, call a service)
agents/audit/services/   business logic and state machines
agents/audit/rules/      deterministic rule evaluators
agents/audit/ai/         prompts, AI output schemas, ML feature builders
agents/audit/models/     SQLAlchemy database models (schema "audit")
agents/audit/schemas/    Pydantic request/response models
agents/audit/workers/    background tasks (async, retryable)
agents/audit/events/     event producers and consumers
agents/audit/tests/      tests
```

### Why `shared/` and not `platform/`?

Python has a built-in module called `platform`. A local folder with the same name would shadow it,
and libraries that do `import platform` would break. So shared services live in `shared/`.

## Tech stack

- Python 3.14 + FastAPI
- PostgreSQL (schema `audit`) with SQLAlchemy 2 + Alembic
- Pydantic v2 + pydantic-settings
- pytest + httpx

## Setup (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Demo (development only)

Needs PostgreSQL running, a `.env` with `ENVIRONMENT=development`, and the tables created (`.venv\Scripts\python -m alembic upgrade head`).

1. Load mock procurement events (PO → GRN → invoice → payment) into the Audit Data Hub:

   ```powershell
   .venv\Scripts\python -m scripts.seed_mock_procurement_events
   ```

   The first run prints `processed` for each event. Running it again prints `duplicate` and adds nothing.

2. Start the server: `.venv\Scripts\python -m uvicorn agents.audit.main:app --reload`
3. Open http://127.0.0.1:8000/docs, choose `GET /api/v1/audit/trail/po/{po_number}`, click "Try it out", and use:
   - `po_number`: `PO-MOCK-00001`
   - `X-User-Id`: any UUID
   - `X-Tenant-Id`: `22222222-2222-2222-2222-222222222222`
   - `X-Roles`: `AUD`

   The response is the PO chain in procure-to-pay order, with `checksum_ok` on each entry.
   The same trail is at http://127.0.0.1:8000/api/v1/audit/trail/po/PO-MOCK-00001, but a plain browser visit returns 401 because it can't send the headers.

## Build progress

### Phase 1 — Audit foundation

- [x] Step 0: Project skeleton (folders, requirements, README)
- [x] Step 1: Scaffold audit package, `audit` schema and Alembic (AUD-001)
- [x] Step 2: Audit roles and permissions — AUD, AM, CO, OWN, MGT (AUD-002) — permission map + API enforcement (401/403) done
- [x] Step 3: Audit Data Hub tables + snapshot service (AUD-003)
- [x] Step 4: Procurement event consumer, against mock events (AUD-004)
- [x] Step 5: Procurement trail builder (AUD-005)
- [ ] Step 6: Frontend `/audit` shell (AUD-006)
- [x] Step 7: CI pipeline
- [x] Exit check: procurement events land in the hub as snapshots
