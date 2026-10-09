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

## Phase 3 demo (development only)

After the Phase 2 demo:

1. `.venv\Scripts\python -m scripts.run_phase3_demo`: puts every demo exception into a case (7 cases), then assigns the CRITICAL case and one HIGH case to the dev user and adds a comment to each. Safe to run again.
2. Start the backend and the frontend, open http://localhost:3000/audit/cases, and choose role **AM**: all 7 cases are listed.
3. The bell (top right) shows the 2 "assigned to you" notifications. Open the **CRITICAL** case.
4. Try the actions: move the status forward, add a comment, and watch the timeline. Closing a HIGH/CRITICAL case needs **AM**.
5. Switch to role **AUD**: only the 2 cases assigned to you are visible.

## Phase 4 demo (development only)

After the Phase 3 demo. The sidebar has a **Dev user** picker: Priya (auditor), Rahul (audit manager) and Sunita (department owner). Pick the user and the matching role together.

1. `.venv\Scripts\python -m scripts.run_phase4_demo`: the PO-DEMO-1 case (PRC-APR-01) goes through the whole loop to CLOSED as a finished example, and the INV-DEMO-5 case (PRC-INVPO-01) gets a finding from Priya that is SUBMITTED and waiting for review. Safe to run again.
2. Start the backend and the frontend. Choose **Rahul** + **AM**, open **Findings**, and open the finding that is UNDER REVIEW.
3. **Confirm** it with Sunita as owner and a due date. Then, under **Corrective actions**, add an action for Sunita.
4. Switch to **Sunita** + **OWN** and open **My Actions**. Open the action, click **Start**, upload a file under **Evidence**, then **Submit for verification**.
5. Switch to **Priya** + **AUD**. Open the action (Findings → the finding → the action), click **Verify**, then on the finding click **Close finding**.
6. Compare with the finished example (the PO-DEMO-1 case): every step is in the case, finding and action timelines.

## Known gaps

- Role notifications (for example "critical case opened" for all Audit Managers) are one shared row: when one manager marks it read, it is read for every manager.
- The Document Service is a local placeholder: files are written to disk before the database commit, so a rolled-back upload leaves an orphan file.
- No action deadline extension or risk acceptance yet (P1).
- No evidence pack ZIP export yet (P1).
- No AI drafting of findings yet (Phase 5).
- The daily job (`scripts.run_daily_jobs`: batch rules + action reminders) exists but is not scheduled yet.
- Once a finding is RESOLVED (every action handed in), no new action can be added to it.
- A case does not change status by itself when its findings and actions move; the auditor moves it.
- Auditee queries and the AI case summary are P1 and not built yet.
- Rule runs triggered by events or the nightly job are recorded in rule-run history but not in the audit log (only API actions are).

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

### Phase 3 — Audit cases

- [x] Append-only audit log; rule changes and runs through the API are logged
- [x] Case state machine (OPEN → … → CLOSED, REOPENED) with full transition tests (AUD-020)
- [x] Case tables and case numbers AUD-YYYY-NNNNN per hospital and year, in hospital time (AUD-020)
- [x] Case service: open, assign, status rules (reason for NO_ISSUE, Audit Manager for HIGH/CRITICAL close), comments, timeline (AUD-020)
- [x] Exceptions open cases automatically, grouped by rule + record within a window; backfill for older exceptions (AUD-021)
- [x] Case API with visibility rules (AM all, AUD own, MGT high-risk, restricted for AM only) and case actions
- [x] Case queue and case workspace UI (AUD-022)
- [x] In-app notifications: case assigned, critical case opened; notification bell (AUD-023)
- [x] Exit check: exceptions become managed cases

### Phase 4 — Findings, evidence and corrective actions

- [x] Placeholder platform services: audit log, notifications, document store with SHA-256 (write once)
- [x] Evidence: upload, system snapshots, links to case/finding/action, fingerprint check on every read, supersede with reason (AUD-030)
- [x] Findings: state machine, structured fields, evidence before submit, maker-checker confirm by an Audit Manager, return, dismiss (AUD-031)
- [x] Finding API with role-based visibility (owners see their own confirmed findings only)
- [x] Corrective actions: owner starts, proves and submits; someone else verifies; the finding follows its actions; case close blocked while anything is open (AUD-032)
- [x] Action reminders (due soon, overdue, escalation) and a daily job script; action API (AUD-032)
- [x] Screens: dev user switcher, evidence tab, findings register and editor, My Actions, action page (AUD-033)
- [x] Exit check: full human audit loop
