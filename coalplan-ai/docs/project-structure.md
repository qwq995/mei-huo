# Project Structure

`coalplan-ai` is organized as a modular construction-organization generation workspace. The backend owns document ingestion, source mapping, outline planning, chapter generation, persistence, and traceability. The frontend is a thin operator workbench for project setup, editable outlines, chapter workspaces, and final Markdown export.

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

- `src/coalplan/web/`: original lightweight frontend.
- `src/coalplan/web1.0/`: current demonstration workbench with template selection, source upload, editable outline tree, source-section modal viewing, chapter version management, supplements, AI proposals, and final merge preview.

`web1.0` is intentionally UI-focused. Source text is shown through a dedicated "view source" modal and is not injected into the chapter preview or final merged document.

## LLM Configuration

LLM providers are selected through environment variables or a local `.env` file. Real keys must never be committed. The common development setup is:

```powershell
COALPLAN_LLM_PROVIDER=deepseek
COALPLAN_DEEPSEEK_BASE_URL=https://api.deepseek.com
COALPLAN_DEEPSEEK_MODEL=deepseek-v4-flash
```

For deterministic tests, use the fake or source-driven LLM implementations.
