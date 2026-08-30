# Project Structure

`coalplan-ai` is organized as a modular construction-organization generation workspace. The backend owns document ingestion, source mapping, outline planning, chapter generation, persistence, and traceability. The frontend is an operator workbench for project setup, editable outlines, chapter workspaces, and final Markdown export.

## Current Entry Points

- Backend: `src/coalplan/main.py`, started from the repository root with `PYTHONPATH=src`; default API address is `http://127.0.0.1:8010`.
- Current frontend: `src/coalplan/web1.0`, default Vite address is `http://127.0.0.1:5173`.
- API documentation: `http://127.0.0.1:8010/docs`.
- Root `.env` is local-only configuration. API keys must remain outside git.

## Backend Layout

```text
src/coalplan/
  domain/             Pure domain models and enums.
  application/        Use cases and pipeline orchestration.
  ports/              Replaceable abstractions for LLM, parsing, storage, retrieval, and queueing.
  infrastructure/     Concrete local implementations for LLM, markdown, retrieval, storage, and validation.
  interfaces/
    api/              FastAPI routes and request/response schemas.
    cli/              Local demo, analysis, audit, and export commands.
  prompts/            Prompt contracts for profile, outline, mapping, generation, repair, and revision.
  assets/             Built-in templates, samples, and reusable generation pattern assets.
```

### Backend Responsibilities

- `domain/`: persisted business objects such as projects, outline nodes, chapter versions, jobs, references, and audits. No HTTP or provider-specific code belongs here.
- `application/`: generation use cases and orchestration. `run_generation_pipeline.py` is the main workflow coordinator; focused modules hold mapping, atom retrieval, skills, audits, and revisions.
- `infrastructure/`: SQLite repositories, local artifacts, Markdown parsing, templates, retrieval, and LLM provider adapters.
- `interfaces/api/`: FastAPI routes and schemas only. Routes should validate input and delegate to application services.
- `interfaces/cli/`: reproducible local tools and one-off evaluation entry points. New experiments should be added here or under `tools/`, not mixed into the domain layer.

## Main Generation Flow

1. Import or upload bid Markdown.
2. Normalize and split the source document into persisted sections and TOC files.
3. Generate a project profile from source sections.
4. Build or refine an editable project outline from the selected template.
5. Estimate target word counts and split dense construction topics before generation.
6. Map every chapter to real source sections and evidence spans.
7. Generate chapter Markdown using the project profile, outline node, mapped source content, supplements, and attachments.
8. Save every AI draft, AI edit, and manual edit as a version.
9. Merge only the user-selected chapter versions into the final Markdown.
10. Run audits as advisory feedback for the next iteration; users decide what to keep.

## Persistence

SQLite is the source of truth for projects, documents, sections, editable outlines, supplements, attachments, versions, proposals, runs, and traces. Large Markdown artifacts and uploaded files are stored under `.coalplan-data/artifacts/` and referenced from the database.

Runtime data, generated comparison outputs, trace directories, and local debug folders are ignored by git.

## Frontends

- `src/coalplan/web1.0/`: current workbench. It contains the five-step workflow, task center, source/atom management, editable outline, chapter generation and Markdown export.
- `src/coalplan/web/`: legacy lightweight frontend kept for historical comparison only. Do not add new features here.

`web1.0` is intentionally UI-focused. Source text is shown through a dedicated "view source" modal and is not injected into the chapter preview or final merged document.

## Runtime Data And Generated Outputs

- `.coalplan-data/`: active local SQLite database and artifacts used by the running API. Treat as user data.
- `.coalplan-*/`, `coalplan-debug*/`, and `coalplan-api-debug-*/`: ignored experiment, smoke-test, and trace output directories. They are not application source and can be archived or removed only after confirming their contents are no longer needed.
- `src/coalplan/web1.0/node_modules/`, `dist/`, `.vite/`, and logs: local frontend runtime output; never edit manually or commit.
- `docs/`: design notes, interface contracts, runbooks, and acceptance records. Generated run reports should use an explicit dated filename.
- `data/`: small, reusable checked-in samples only. Large real projects belong in local runtime data, not this directory.

## Maintenance Rules

- New product code goes under the existing backend layers or `web1.0/src`; do not create a second frontend or a parallel API implementation.
- Keep one active frontend entry: `src/coalplan/web1.0`. The legacy `web` directory is read-only unless a comparison task explicitly needs it.
- Keep experiments out of source directories. Use an ignored `.coalplan-<purpose>-<date>/` directory and record the command and input in a short report under `docs/` when the result is reusable.
- Do not manually edit `.coalplan-data/`, database files, `dist/`, or `node_modules/`. Use the API, migration scripts, or package manager.
- Before delivery, run backend syntax checks, frontend tests, TypeScript compilation, and `git diff --check`.

## LLM Configuration

LLM providers are selected through environment variables or a local `.env` file. Real keys must never be committed. The common development setup is:

```powershell
COALPLAN_LLM_PROVIDER=deepseek
COALPLAN_DEEPSEEK_BASE_URL=https://api.deepseek.com
COALPLAN_DEEPSEEK_MODEL=deepseek-v4-flash
```

For deterministic tests, use the fake or source-driven LLM implementations.
