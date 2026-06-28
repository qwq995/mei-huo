# Pattern Library API

These endpoints expose the reusable local construction-organization writing skill generated from the user's local construction organization corpus.

The pattern library is writing guidance only. It must not be treated as a project factual source. Project facts still come from mapped `section_id`, `evidence_id`, user supplements, or manual placeholders.

## `GET /pattern-library`

Returns the currently active pattern library.

Response fields:

- `library.version`
- `library.corpus_scope`
- `library.patterns`
- `active_path`
- `generated_path`
- `generated_available`

## `POST /pattern-library/analyze`

Analyzes a local construction organization TOC corpus and writes reviewable artifacts. This does not overwrite the active `writing_patterns.json`.

Request:

```json
{
  "corpus_dir": "C:\\Users\\Lenovo\\Documents\\coalplan-corpus",
  "output_dir": ".coalplan-data\\pattern-library"
}
```

Both fields are optional. When omitted:

- `corpus_dir` uses the default local corpus directory.
- `output_dir` uses the current runtime storage directory under `pattern-library/`.

Response:

```json
{
  "analysis": {},
  "generated_library": {},
  "corpus_dir": "...",
  "analysis_json_path": ".../local-corpus-analysis.json",
  "analysis_markdown_path": ".../local-corpus-analysis.md",
  "generated_path": ".../writing_patterns.generated.json"
}
```

## `POST /pattern-library/build-skill`

Runs the complete review-only local corpus skill build in one request:

1. analyze local construction-organization corpus;
2. build `writing_patterns.generated.json`;
3. audit pattern-library coverage;
4. export a reusable skill package with `SKILL.md`, prompt cards, pipeline references, coverage report, and manifest.

The default build derives reusable body-writing cues from TOC headings, for example process flow, quality inspection loops, safety risk controls, environmental categories, and schedule/resource guarantees. When `include_source_excerpts=true`, the backend also tries to read original PDF/DOCX files referenced by the corpus headers to enrich those cues. This can be slower and is best used when the source files are locally available.

Request:

```json
{
  "corpus_dir": "C:\\Users\\Lenovo\\Documents\\煤火\\施组目录结构_纯文本",
  "output_dir": ".coalplan-data\\pattern-library\\reviewable-skill-build",
  "skill_name": "construction-org-writing-patterns",
  "include_source_excerpts": false,
  "max_source_chars": 250000
}
```

Response includes:

- `analysis_json_path`
- `analysis_markdown_path`
- `generated_path`
- `coverage_json_path`
- `coverage_markdown_path`
- `skill_package_dir`
- `skill_manifest_path`
- `skill_package.manifest.coverage_status`

This endpoint does not apply the generated library. Use `/pattern-library/apply-generated` only after reviewing the generated pattern library, coverage report, and skill package.

## `GET /pattern-library/generated`

Previews a generated pattern library. Pass `generated_path` to preview a runtime artifact:

```text
GET /pattern-library/generated?generated_path=.coalplan-data/pattern-library/writing_patterns.generated.json
```

If `generated_path` is omitted, the endpoint tries the package-level `writing_patterns.generated.json`.

## `POST /pattern-library/audit`

Audits whether an active or generated writing-pattern library is broad and deep enough to act as a reusable construction-organization writing skill. This is a review gate before `apply-generated`; it does not modify the active library.

Request:

```json
{
  "generated_path": ".coalplan-data\\pattern-library\\writing_patterns.generated.json",
  "library": {},
  "corpus_dir": "C:\\Users\\Lenovo\\Documents\\coalplan-corpus",
  "output_dir": ".coalplan-data\\pattern-library"
}
```

- `generated_path` audits a generated candidate.
- `library` audits an inline library object, useful for offline review.
- if neither is provided, the active library is audited.
- `corpus_dir` is optional; when provided, the audit also checks whether the latest local corpus supports each required pattern.

Response:

```json
{
  "report": {
    "status": "passed|warning|blocked",
    "summary": "...",
    "metrics": {},
    "pattern_audits": [],
    "issues": [],
    "recommendations": []
  },
  "library": {},
  "source_path": ".../writing_patterns.generated.json",
  "corpus_dir": "...",
  "artifact_json_path": ".../pattern_library_coverage.json",
  "artifact_markdown_path": ".../pattern_library_coverage.md"
}
```

Audit policy:

- missing required patterns (`overview`, `deployment`, `craft`, `quality`, `safety`, `environment`, `schedule_resource`) block reuse;
- thin `preferred_structure` or `required_source_facts` blocks or warns because the model cannot reliably map sources or allocate detail;
- missing `human_only_items`, `revision_signals`, or local heading seeds warns because later generation may invent facts or fail to trigger remap/split/regenerate;
- corpus support warnings mean the skill can still be reviewed, but more local human-written samples should be added before broad reuse.

## `POST /pattern-library/learn-from-quality-iteration`

Builds a reviewable pattern-library candidate from a quality-iteration learning report. This is the bridge from real generation failures back into the reusable writing skill. It does not overwrite the active `writing_patterns.json`.

Request can use one of three sources:

```json
{
  "project_id": "project_xxx",
  "learning_report_path": ".coalplan-data/artifacts/project_xxx/control/quality_iteration_learning.json",
  "learning_report": {},
  "selected_suggestion_indexes": [0, 2, 3],
  "output_dir": ".coalplan-data\\pattern-library"
}
```

- Use `project_id` after `POST /projects/{project_id}/quality-iteration`.
- Use `learning_report_path` for an exported report.
- Use `learning_report` for tests or offline review.
- Use `selected_suggestion_indexes` to rebuild the candidate from only accepted learning suggestions.

Response:

```json
{
  "learning_report": {},
  "generated_library": {},
  "changes": [],
  "selected_suggestion_indexes": [0, 2, 3],
  "source": "quality_iteration_learning",
  "generated_path": ".../writing_patterns.learning.generated.json",
  "learning_report_path": ".../quality_iteration_learning_report.json",
  "learning_candidate_markdown_path": ".../quality_iteration_learning_candidate.md"
}
```

Learning merge policy:

- omitted source facts strengthen `required_source_facts` only after being generalized, for example project-specific pressure values become `控制参数`;
- missing human-reference headings become `corpus_common_headings`;
- repeated regenerate/rewrite targets become `revision_signals`;
- subsection-level weak source, missing source, rewrite, human-input, and split targets from `content_revision_plan` become `revision_signals` or detail/split guidance;
- generation-metadata organization-audit targets add missing local-pattern organization points to outline guidance and turn `expand_subsections` into split/detail guidance;
- detail or split problems become detail-budget and subsection-split guidance.

The original evidence is kept under `corpus_basis` and in the candidate Markdown for review. Apply it only after inspection with `POST /pattern-library/apply-generated`.

Workbench flow:

1. Run a project quality iteration from the pipeline actions.
2. In the writing-pattern panel, click `质量迭代学习`.
3. Review the displayed candidate changes and the `quality_iteration_learning_candidate.md` artifact.
4. Use `预览生成库` or `导出 skill` to inspect the candidate prompt form.
5. Click `应用生成库` only after accepting the candidate; the backend creates a backup of the active library first.

Selection workflow: after `质量迭代学习`, uncheck unwanted candidate changes and click `按选择重建候选库`; the rebuilt candidate sends `selected_suggestion_indexes` and still requires explicit `应用生成库` before the active library changes.

The frontend also exposes `导出 skill 包`, which calls the same export endpoint with `output_dir` and writes `SKILL.md`, `references/writing-pattern-cards.md`, `references/pipeline-blueprint.md`, `references/pipeline-control.md`, `references/pattern-library-coverage.md`, and `manifest.json`.

## `GET /pattern-library/skill`

Renders the active pattern library as a reviewable Markdown writing skill. This is the text form intended for prompt injection or human review.

Optional query:

```text
GET /pattern-library/skill?generated_path=.coalplan-data/pattern-library/writing_patterns.generated.json
```

Response:

```json
{
  "library": {},
  "markdown": "# Construction Organization Writing Skill\n...",
  "validation_issues": [],
  "coverage_report": {},
  "output_path": null
}
```

The rendered skill repeats the rule that corpus patterns are not factual evidence. Generation must still cite mapped source sections and evidence IDs.
The response includes `coverage_report`, so the UI can show whether the skill is fit for reuse before exporting or applying a generated library.

## `POST /pattern-library/skill/export`

Writes either the rendered Markdown skill to a local file, or a reusable skill package with `SKILL.md` plus references.

Request:

```json
{
  "generated_path": ".coalplan-data\\pattern-library\\writing_patterns.generated.json",
  "output_path": ".coalplan-data\\pattern-library\\construction-org-writing-skill.md",
  "output_dir": ".coalplan-data\\pattern-library\\construction-org-writing-patterns"
}
```

`generated_path` is optional. If omitted, the active library is exported.

- Use `output_path` for a single reviewable Markdown file.
- Use `output_dir` for a skill package containing:
  - `SKILL.md`
  - `references/writing-pattern-cards.md`
  - `references/pipeline-blueprint.md`
  - `references/pipeline-control.md`
  - `references/pattern-library-coverage.md`
  - `manifest.json`

When `output_dir` is provided, the response includes `package_paths` and `manifest`.
The manifest includes `coverage_status`, `coverage_issue_count`, and the full `coverage_report`, making the exported skill package a self-contained review artifact.

## `POST /pattern-library/apply-generated`

Applies a generated pattern library after human review. The backend validates the generated JSON, backs up the active pattern library, writes the new active library, and clears the pattern-library cache.

Request:

```json
{
  "generated_path": ".coalplan-data\\pattern-library\\writing_patterns.generated.json"
}
```

Response:

```json
{
  "applied": true,
  "applied_at": "2026-06-26T12:00:00",
  "active_path": "src/coalplan/assets/generation/writing_patterns.json",
  "generated_path": ".../writing_patterns.generated.json",
  "backup_path": "src/coalplan/assets/generation/writing_patterns.20260625-120000.bak.json",
  "apply_log_path": "src/coalplan/assets/generation/writing_patterns.apply-log.json",
  "apply_history_path": "src/coalplan/assets/generation/writing_patterns.apply-history.json",
  "apply_history_count": 3,
  "coverage_status": "passed|warning|blocked",
  "coverage_issue_count": 0,
  "coverage_report": {},
  "library": {}
}
```

The apply log records the latest generated source, backup path, applied time, library version, corpus scope, and pattern count. The apply history keeps all accepted apply events in chronological order so quality-iteration learning and manual acceptance remain traceable after the active skill changes.
The apply log and apply history also persist the coverage status from the moment of application, so later generation traces can be interpreted against the exact skill quality gate that was active.

## `GET /pattern-library/apply-history`

Returns the chronological apply history for the active pattern library.

Response:

```json
{
  "history": [
    {
      "applied": true,
      "applied_at": "2026-06-26T12:00:00",
      "active_path": "src/coalplan/assets/generation/writing_patterns.json",
      "generated_path": ".../writing_patterns.learning.generated.json",
      "backup_path": "src/coalplan/assets/generation/writing_patterns.20260625-120000.bak.json",
      "library_version": "quality-iteration-20260626",
      "corpus_scope": "local corpus + accepted quality iteration",
      "pattern_count": 8
    }
  ],
  "apply_history_path": "src/coalplan/assets/generation/writing_patterns.apply-history.json"
}
```

Recommended workflow:

1. `GET /pattern-library` to inspect the active writing skill.
2. `POST /pattern-library/analyze` after local corpus files change.
3. `POST /pattern-library/learn-from-quality-iteration` after real project quality iterations produce learning reports.
4. `GET /pattern-library/generated` to review the generated skill.
5. `GET /pattern-library/skill` to preview the Markdown prompt form.
6. `POST /pattern-library/skill/export` to persist either the prompt form or the reusable skill package.
7. `POST /pattern-library/apply-generated` only after the generated skill is accepted.

CLI package export:

```powershell
$env:PYTHONPATH='src'
python -m coalplan.interfaces.cli.export_pattern_skill --output-dir .coalplan-data\pattern-library\construction-org-writing-patterns
```

One-command reviewable build from the local corpus:

```powershell
$env:PYTHONPATH='src'
python -m coalplan.interfaces.cli.build_pattern_skill `
  --corpus-dir "C:\Users\Lenovo\Documents\煤火\施组目录结构_纯文本" `
  --output-dir .coalplan-data\pattern-library\reviewable-skill-build
```

This command writes:

- `local-corpus-analysis.json/md`
- `writing_patterns.generated.json`
- `pattern_library_coverage.json/md`
- `construction-org-writing-patterns/SKILL.md`
- `construction-org-writing-patterns/references/writing-pattern-cards.json`
- `construction-org-writing-patterns/references/pipeline-blueprint.md`
- `construction-org-writing-patterns/manifest.json`

It is review-only and does not replace the active `src/coalplan/assets/generation/writing_patterns.json`. Apply the generated library separately after inspection.
