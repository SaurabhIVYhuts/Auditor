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

4. Or use the frontend: keep the backend (uvicorn) running in one terminal. In a second terminal run:

   ```powershell
   cd frontend
   npm run dev
   ```

   Then open http://localhost:3000/audit.

## Phase 2 demo (development only)

Same requirements as above. Then:

1. `.venv\Scripts\python -m scripts.seed_rule_pack`: adds the 11 procurement rules to the demo hospital and activates them (author and approver are two different dev users).
2. `.venv\Scripts\python -m scripts.run_phase2_demo`: sends demo procurement events. The first run creates 7 exceptions; running it again creates 0.
3. Start the backend and the frontend (as above), open http://localhost:3000/audit/rules, and choose role **AM** in the sidebar.
4. Open **PRC-APR-01** and look at **Run history**: it lists one EVENT run per demo PO event, and the run for PO-DEMO-1 shows 1 exception created.

## Build progress

### Phase 1 — Audit foundation

- [x] Step 0: Project skeleton (folders, requirements, README)
- [x] Step 1: Scaffold audit package, `audit` schema and Alembic (AUD-001)
- [x] Step 2: Audit roles and permissions — AUD, AM, CO, OWN, MGT (AUD-002) — permission map + API enforcement (401/403) done
- [x] Step 3: Audit Data Hub tables + snapshot service (AUD-003)
- [x] Step 4: Procurement event consumer, against mock events (AUD-004)
- [x] Step 5: Procurement trail builder (AUD-005)
- [x] Step 6: Frontend `/audit` shell (AUD-006)
- [x] Step 7: CI pipeline
- [x] Exit check: procurement events land in the hub as snapshots

### Phase 2 — Rules engine

- [x] Rule, rule version and config tables; rule registry with versioning (AUD-010)
- [x] Rule DSL: whitelist, validator and evaluator with three-valued logic (AUD-011)
- [x] Event-triggered and batch rule runs, with run history (AUD-012)
- [x] Exceptions with dedup, so a rule never flags the same record twice (AUD-013)
- [x] Procurement rule pack: 11 starter rules, seeded as DRAFT, with behaviour tests (AUD-014)
- [x] Rule library UI: list and detail pages with activate / deactivate / run now (AUD-015)
- [x] Rule API with maker-checker activation (AUD-010)
- [x] Exit check: rules produce exceptions from procurement events
