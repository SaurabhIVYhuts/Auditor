# CLAUDE.md

## Project

This is the **Konnective Tissue AI Auditor Agent**, a standalone **public** repository.

The architecture reference is `C:\KonnectiveTissue\docs\auditor-architecture.pdf` (internal document, outside this repo).
Read it when needed, but **never copy it into this repo and never paste large parts of it here**.

## Folder layout

- `shared/` — placeholders for platform services (auth/RBAC, audit log, documents, notifications, AI gateway), to be swapped for the real platform later. It is not named `platform/` because that would shadow Python's built-in `platform` module.
- `agents/audit/` — the agent itself, following section 7.1 of the PDF: `api/`, `services/`, `rules/`, `ai/`, `models/`, `schemas/`, `workers/`, `events/`, `tests/`.

## Design rules

- AI only recommends; humans decide. Chain: **Anomaly → Risk → Human Review → Finding**. AI never changes a status.
- Read-only on all source systems (Procurement, Insurance, ERP, HIS). Store snapshots and references only.
- Neutral language: "exception", "anomaly", "observation", "finding". Never "fraud".
- Rules before AI: if it can be a deterministic rule, make it a rule.
- No hard-coded thresholds, weights or SLAs. Put them in config.
- Every finding needs at least one piece of evidence.
- Maker-checker: the person who creates something cannot approve it.

## Tech

- Python 3.14, FastAPI, PostgreSQL (schema `audit`), SQLAlchemy 2 + Alembic, pytest.
- OS is Windows; terminal is PowerShell. The virtual environment is `.venv` (`.venv\Scripts\python`).

## Working style

- The developer is a beginner. Work one small step at a time.
- Before changing important files, explain what you will do and why, in simple language.
- Run the tests after each step.
- Never commit or push unless asked.
