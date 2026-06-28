# 施工组织设计生成控制流水线

## 目标

把“输入文档切章 -> 目录树生成 -> 来源映射 -> 逐章正文生成”升级为可控流水线。控制层不直接写正文，而是决定：

- 投标文档里有的信息是否被目录承接。
- 当前目录节点是否需要拆成更小章节。
- 每章目标字数、证据容量和展开深度。
- 来源不足、格式失败、正文空泛或疑似编造时应采取哪种修订动作。

## 分层

```text
domain/generation_control.py
  纯模型：Coverage、ChapterPolicy、RevisionTrigger、GenerationControlPlan

application/generation_control_plan.py
  启发式控制计划：先不依赖 LLM，也可作为 LLM 控制结果的兜底

prompts/*_audit / *_plan / *_decision
  LLM 控制提示词：输出严格 JSON，供后端校验后应用

application/run_generation_pipeline.py
  编排入口：后续接入控制计划，不让 generate_chapter 承担决策
```

## 推荐流程

1. 输入规范化与切章，持久化 `toc.json`、`sections.json`、`sections/*.md`。
2. 生成项目概况；无效 `source_section_id` 应清洗，而不是丢弃整份画像。
3. 读取模板目录树，生成项目目录初稿。
4. 执行目录覆盖审计：
   - 投标目录有、项目目录无：建议新增或并入节点。
   - 项目目录有、投标目录无：禁用或要求人工补充。
   - 通用施组章节缺失：提示补齐施工部署、临建、进度、资源、质量、安全、环保、文明、应急。
5. 对每个可生成节点生成 `ChapterGenerationPolicy`：
   - 工艺章节提高来源匹配数和证据片段数。
   - 大章或高密度章节先拆小节。
   - 拆小节优先从输入 `toc.json` 中派生：当父章命中钻孔、灌浆、混凝土、支护、开挖、爆破、注水、覆盖封堵等工艺词时，扫描源目录下的真实叶子标题，如“帷幕灌浆施工”“黄泥注浆施工”“套管施工措施”“灌浆施工质量检查”，写入 `source_subtopics`。
   - 空来源章节默认不生成确定正文。
6. 逐小节来源映射：
   - 先用目录判断候选章节。
   - 再从章节全文抽取 evidence span。
   - evidence_id 必须进入 prompt 和 trace。
   - 从 evidence span 中抽取 `required_source_facts`：数字+单位、日期、规范编号、压力、流量、孔深、孔径、配比、压实度、温度、间距、厚度等可核验事实。
7. 逐小节生成正文。
   - 生成 prompt 会按章节类型注入“施组写作模式参考”，包括工艺、质量、安全、环保、进度资源、工程概况、施工部署等结构化写法。
   - 写作模式只作为组织正文的骨架，不作为事实来源；事实仍必须来自来源章节、evidence、用户补充或人工占位。
   - 人类施组样本的作用是学习“目录放在哪里、每类章节按什么顺序展开、工程/安全/质量/环保应覆盖哪些要点、检查整改闭环怎么组织”，不是追求生成文段与人类参考逐字一致。
   - 质量目标应从“像不像某篇人类文档”转为“当前项目证据是否被放进了合适的施组组织形式中”。
   - `required_source_facts` 会作为单独清单进入 prompt，模型必须优先写入“生成正文”；确因章节范围不适用而不写时，应在“人工补充需补充”说明原因。
8. 执行修订判定：
   - 格式错：repair。
   - 来源错：remap。
   - 已映射原文中的必保留事实未进入正文：regenerate。
   - 空泛：expand_subsections 或 regenerate。
   - 无来源：request_human_input 或 disable。
   - 判定结果持久化为 `control/revision_decisions.json` 和 `control/revision_decisions.md`，并通过 `GET /projects/{id}/revision-decisions` 供前端查看。
9. 通过后进入版本库，合并时只使用用户选中的版本。
10. 生成后做覆盖报告，列出未被正文利用的高价值输入章节。
11. 执行组织要点覆盖审计：按本地 pattern 检查生成稿是否覆盖工程概况、施工部署、工艺、质量、安全、环保、进度资源等章节应有的组织要点；该审计不要求与人类文段一致，只判断是否用当前项目证据填充了合适的施组组织形式。
12. 对每个选中章节版本执行正文小节级修订计划：从 `content_tree` 中读取生成正文叶子小节，判断该小节应 `accept`、`review_source_link`、`remap_sources`、`rewrite_subsection`、`request_human_input` 或 `split_subsection`。若版本存在 `evidence_audit.omitted_required_fact_ids`，这些遗漏事实会先投射到最相关小节，形成 evidence-targeted `rewrite_subsection`。该计划持久化为 `content_revision_plan.json/md`，并回流到版本门禁和下一步动作计划。

## 施组章节详略策略

工艺类章节按以下顺序展开：

1. 适用范围和施工对象。
2. 工艺流程。
3. 人员、设备、材料和作业条件。
4. 施工方法和控制参数。
5. 质量检查与验收。
6. 安全、环保、文明施工控制。
7. 缺失参数占位。

管理保障类章节按以下顺序展开：

1. 目标。
2. 组织体系。
3. 岗位职责。
4. 制度与流程。
5. 过程控制措施。
6. 检查、考核、纠偏闭环。
7. 需人工确认的项目级信息。

## 强制控制规则

- 目录覆盖审计在正文生成前执行。
- 质量审计中的人类字数比和标题覆盖率只作为辅助信号；主要修订依据应是 source fact absorption、organization pattern coverage、trace diagnostics 和章节合同校验。
- `source_mapping.matches` 为空时，默认不得生成确定事实正文。
- 若 `source_mapping.matches` 为空且 `ChapterGenerationPolicy.generate_when_no_source=false`，pipeline 应跳过 LLM 正文生成，写出 `no_source_mapping` 失败草稿，修订决策为 `request_human_input`，供用户补充来源或禁用节点。
- `required_source_facts` 的利用审计只看“生成正文”正文块；仅在“主要来源摘要”列出 `evidence_id` 不算正文已经吸收。
- 原文里存在的工程量、参数、日期、规范编号等事实，如果正文遗漏，应触发 `omitted_required_source_facts -> regenerate`。
- `target_word_count` 不得强迫模型编造，来源不足时要降低详略或要求人工补充。
- 大章生成结果若只有概括段落，应触发 `expand_subsections`。
- 正文小节树里的叶子小节若有事实性内容但 `source_status=missing`，应触发 `remap_sources`；若仅有弱来源，应触发 `review_source_link`；若已有来源但低于小节详略要求，应触发 `rewrite_subsection`；若含人工占位，应触发 `request_human_input`。
- 版本门禁不仅检查是否选择了章节版本，也检查选中版本的 `content_revision_plan` 是否存在未处理动作；有 LLM 动作时，`pipeline-actions` 会把版本审阅动作标记为 `requires_llm=true`。
- 小节级修订动作通过 `POST /projects/{id}/chapters/{node_id}/versions/{version_id}/content-nodes/{content_node_id}/revision-action` 执行：`remap_sources/review_source_link/rewrite_subsection` 会重新召回来源、构造只允许输出当前小节 Markdown 的 prompt、保存 trace，并创建新的章节版本；`request_human_input` 只返回补充资料要求；`split_subsection` 会创建可确认的 outline proposal，应用后拆出的子节点作为普通目录节点进入逐节点来源映射和生成流程，不直接覆盖正文。
- 高密度工艺章若已有 `source_subtopics`，目录 proposal 应优先使用源目录子题，而不是只使用固定模板子题。
- 所有修订动作先产生 proposal 或新版本，不覆盖用户已选版本。

## 本地施组模式库

本地施组经验不作为项目事实来源，而作为“章节写法 skill”注入单章生成 prompt。当前数据资产位于：

- `src/coalplan/assets/generation/writing_patterns.json`
- `src/coalplan/application/writing_pattern_library.py`

模式库按章节类型沉淀为 `overview / deployment / craft / quality / safety / environment / schedule_resource` 等 pattern。每个 pattern 包含：

- `preferred_structure`：推荐正文展开顺序。
- `required_source_facts`：本类章节生成时应优先从 evidence 中吸收的事实类型。
- `auto_writable_moves`：模型可以做的归纳、组织、润色动作。
- `human_only_items`：必须由图纸、审批、合同、现场实测、人员设备表等人工确认的内容。
- `revision_signals`：生成后触发重写、拆章或人工补充的症状。
- `corpus_basis`：来自本地 34 份施组目录统计的依据。
- `organization_policy`：明确本地施组样本只用于学习目录位置、小节顺序、要点覆盖和检查闭环，不用于复刻人类文段。

单章生成时的事实优先级保持不变：

1. 映射原文 `section_id/evidence_id`。
2. 用户在章节工作区补充的文本、表格和附件说明。
3. 模板四模块。
4. 本地施组模式库只提供写作骨架和质量预期，不得补造工程量、参数、工期、坐标、审批结论或验收结论。

与修订决策的关系：

- 若模式库要求的 `required_source_facts` 在 evidence 中存在，但正文未吸收，证据利用率审计会推动 `regenerate`。
- 若组织要点覆盖率偏低，`organization_pattern_audit` 会推动 `repair_outline_coverage`、`expand_subsections` 或 `regenerate`，要求补齐对象、范围、流程、资源、质量、安全、环保、验收、人工缺项等该类章节应有要点。
- 若正文把 `human_only_items` 写成确定事实，质量门应判定为疑似编造。
- 若 `craft` 类章节目标字数高、证据多、但未拆成小节，控制计划应推动 `expand_subsections`。

## 刷新本地语料模式

项目内提供了本地施组目录语料分析 CLI：

```bash
PYTHONPATH=src python -m coalplan.interfaces.cli.analyze_local_corpus
```

可选增强：在本地源 PDF/DOCX 可访问时，读取原始施组正文片段并抽取通用写作线索：

```bash
PYTHONPATH=src python -m coalplan.interfaces.cli.analyze_local_corpus --include-source-excerpts --max-source-chars 180000
```

该增强只提取正文组织方式，例如工艺流程组织、质量检查闭环、安全应急结构、环保分类措施、进度资源保障等，写入 `auto_writable_moves` 和 `revision_signals`。它仍然不是项目事实来源；真实生成中的工程量、参数、日期、标准、审批和验收结论必须继续来自输入文档映射出的 `section_id/evidence_id`、用户补充或人工占位。

默认读取：

```text
C:\Users\Lenovo\Documents\煤火\施组目录结构_纯文本
```

默认输出：

- `docs/local-corpus-analysis.json`
- `docs/local-corpus-analysis.md`
- `src/coalplan/assets/generation/writing_patterns.generated.json`

推荐流程：

1. 本地新增或更新施组目录样本后，先运行 `analyze_local_corpus`。
2. 审阅 `docs/local-corpus-analysis.md` 的项目类型、章节高频标题、pattern 覆盖。
3. 审阅 `writing_patterns.generated.json` 的 `corpus_basis` 是否合理。
4. 确认无误后，再人工或脚本替换正式 `writing_patterns.json`。

这样“预训练 skill”保持可追溯：生成时使用的是稳定版本 `writing_patterns.json`，刷新时先生成 `writing_patterns.generated.json` 供检查，不直接覆盖线上生成规则。
## Editable Outline Task Sync

The editable project outline is the source of truth for generation tasks. Whenever an outline proposal is applied, and before directory preparation, full generation, single-chapter generation, or merge, the latest `generation run` is synchronized from the current outline:

- new repair or split nodes become normal `chapter_tasks` and can be source-mapped, generated, versioned, revised, and merged;
- removed, disabled, or non-generatable nodes leave the current task view, while existing version records remain available in the workspace;
- generated nodes whose title or target word count changed are marked `needs_repair` so stale text is not silently accepted;
- the apply-proposal API returns `chapter_task_count`, or `task_sync_warning` if the directory change was saved but task synchronization needs attention.

This keeps directory-tree iteration, subsection splitting, and chapter generation decoupled: outline editing only changes outline nodes, task sync derives executable work, and generation still performs mapping and evidence checks per node.

## Generation Metadata

Every generated chapter version now persists `generation_metadata.json` beside the version artifacts. This metadata records the reusable local writing patterns that shaped the chapter, without treating those patterns as facts:

- `selected_pattern_keys`: matched local construction-plan pattern cards such as `craft`, `quality`, `safety`, or `overview`;
- `writing_guidance`: chapter type, recommended organization order, focus points, avoid rules, and local-corpus basis;
- `local_pattern_matches`: pattern-library matches from the local corpus card set;
- `generation_policy`: target word count, detail level, source/evidence budgets, and subsection split policy;
- `pattern_evidence_scope`: the invariant that corpus patterns are structural only and project facts must come from mapped `section_id/evidence_id`, user supplements, or manual placeholders;
- `non_factual_pattern_rules`: rules preventing unsupported project facts from being copied out of templates or human references.

The metadata is exposed through `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}/generation-metadata`. The response includes the raw metadata plus an `organization_audit` block with `status`, `issues`, `next_actions`, `metrics`, and per-pattern audits. Quality audit and future frontend panels can use it to explain why a chapter was organized in a certain way and whether the selected pattern expects more source-backed facts before regeneration.

The version gate now uses this metadata as a control signal. A selected version without `generation_metadata` is not fully traceable, so the gate reports `selected_version_missing_generation_metadata`. When metadata is present, the gate audits the selected `pattern_keys` against the generated markdown organization points; low coverage becomes `selected_version_pattern_revision_actions`, with LLM-required actions counted separately. `pipeline-actions` exposes this as `version.review_generation_metadata`, pointing to the generation-metadata endpoint so the UI can show whether the next step is inspection, subsection expansion, or regeneration.

The metadata audit is also executable through `POST /projects/{project_id}/chapters/{node_id}/versions/{version_id}/generation-metadata/revision-action`. This endpoint keeps the action aligned with the existing control pipeline:

- `regenerate` calls the normal single-chapter generation path and injects a revision context rendered from the metadata audit, so retries carry the missing pattern points, metrics, and source-grounding rules.
- `expand_subsections` and `repair_outline_coverage` create editable outline proposals instead of silently rewriting the project directory.
- `request_human_input` returns a workbench instruction without calling the LLM when the missing item is a drawing, approval, site measurement, parameter, table, or attachment note.
- `accept` records that the selected version passes the generation-metadata control gate and needs no automatic change.

This closes the loop from local corpus pattern selection to pattern audit to controlled revision: patterns remain non-factual writing structure, while all regenerated project facts still have to come from mapped source sections, evidence spans, user supplements, or manual placeholders.

Local corpus body-writing cues now participate in this gate. The pattern skill learns reusable organization cues from the local corpus, such as craft chapters covering construction preparation, setting out, process flow, process control, inspection and acceptance; quality chapters covering objective, assurance system, responsibility, three-inspection process, acceptance and rectification; safety chapters covering hazards, technical disclosure, site inspection and emergency response. When a generated version misses these cue groups, the metadata audit routes the issue by action instead of asking for a blind rerun:

- dense craft cue gaps -> `expand_subsections`;
- management-control cue gaps -> `regenerate` with missing cue requirements in the prompt context;
- source-free or human-only cue gaps -> `request_human_input`.

These cues are structural guidance only. The retry still has to use mapped `section_id/evidence_id`, user supplements, or manual placeholders for factual project content.

When the executable metadata revision endpoint receives `expand_subsections`, it now creates an editable outline proposal that carries the missing cue groups into child-node `source_rules`, `auto_fill`, `manual_fill`, and `special_notes`. After the proposal is applied, task synchronization treats those child nodes as normal generation work: each child must map source sections, extract evidence, generate a version, pass metadata/evidence/content-tree gates, and be selected before merge. The original selected version is not overwritten by this split proposal.

The branch-level execution endpoint `POST /projects/{project_id}/chapters/{node_id}/children/generate` continues this flow after proposal application. It generates the confirmed child nodes under a parent chapter by repeatedly calling the existing single-chapter pipeline, so tree-branch generation stays decoupled from full-project generation while preserving the same mapping, evidence, prompt trace, validation, and version gates.

`pipeline-actions` now detects these branch-level opportunities. When an applied split creates child outline nodes that already have generation tasks but lack selected versions, the action plan emits `generation.child_branch.{parent_node_id}` with `action=generate_child_chapters` and endpoint `POST /projects/{project_id}/chapters/{parent_node_id}/children/generate`. The generic full-project generation action remains available as a fallback, but the UI can advance only the affected branch after a split.

`generation-readiness` complements those actions with a per-node scheduling index. `GET /projects/{project_id}/generation-readiness` reads the editable outline, control policies, latest source mappings, task statuses, selected versions, persisted `revision_decisions`, and `GenerationControlPlan.revision_triggers`, then classifies each node as `has_children`, `split_required`, `needs_mapping`, `needs_human_input`, `ready_to_generate`, `needs_revision`, or `ready_for_merge`. When a revision decision is still open, the readiness node carries `revision_decision`, `revision_reasons`, and `required_changes`, so a chapter with a selected version is not treated as merge-ready until remap/regenerate/repair/request-human-input is resolved. Quality-feedback triggers are also converted into readiness decisions when they target a concrete node; `all_chapters` only marks chapters that already have a selected version or passed task, which keeps the loop incremental instead of regenerating untouched chapters. It writes `control/generation_readiness.json` and `.md`, giving the frontend a stable explanation for why a node should be split, supplemented, generated, revised, or merged before any LLM call is made.

The same readiness report also returns `batches`: `auto_generation`, `auto_revision`, `user_confirmation`, `merge_review`, and `structure_only`. This keeps bulk scheduling decoupled from the UI. A future queue can run only `execution_mode=auto` batches, while user-confirmation batches stop at proposal, supplement, or disable decisions.

`POST /projects/{project_id}/generation-readiness/execute` is the bounded executor for those batches. By default it runs only auto batches and skips user-confirmation items. Each item delegates to the existing single-chapter generation, child-branch generation, or revision-action endpoint, then writes `control/generation_readiness_batch_execution.json` and `.md` with executed/skipped/failed items plus pre-run and post-run readiness snapshots. This makes batch execution traceable without creating a second generation pipeline.

`pipeline-actions` now promotes this loop into project-level orchestration. When the version gate can identify the selected chapter version that failed metadata audit, the action is emitted as `version.review_generation_metadata.{node_id}.{version_id}` with `target_id`, `target_version_id`, `source_decision`, and a concrete POST endpoint. The frontend can therefore run the metadata revision directly from the project "next action" panel; if the target version cannot be resolved, the action remains a review prompt and the user is sent to the chapter workspace first.

The same targeting now applies to generated content subsections. If a selected version has a `content_revision_plan` item such as `remap_sources`, `review_source_link`, `rewrite_subsection`, `split_subsection`, or `request_human_input`, `pipeline-actions` emits `version.review_content_tree_sources.{node_id}.{version_id}.{content_node_id}` with a concrete POST endpoint. When the item comes from omitted evidence-audit facts, the action title is marked as evidence-targeted and the version gate increments `selected_version_evidence_targeted_content_revision_actions`. This lets the project-level runner execute subsection repair without losing the traceable node/version/content-node boundary.

## Revision Context Loop

When a chapter revision decision is `regenerate`, `remap_sources`, or `repair_format`, the next generation call must not reuse the same prompt unchanged. The pipeline renders the revision decision into a stable prompt block that includes:

- decision action and severity;
- decision reasons and required changes;
- missing evidence;
- omitted `required_source_facts`, including `fact_id`, `evidence_id`, `section_id`, and fact text;
- unused high-value evidence ids;
- manual-fill items that appear to have support in mapped source evidence.

This block is appended to the chapter workspace context before calling the LLM. The rule is reusable across project types: the revision agent decides what failed, while the generation agent receives concrete correction requirements and source facts to absorb or explicitly mark as human-supplemented.

## Post-Generation Quality Audit

After a full generation run, execute the reusable quality audit before accepting the result as a baseline:

```powershell
$env:PYTHONPATH='src'
python tools\audit_generation_quality.py --input-root 'C:\Users\Lenovo\Desktop\示例输入输出' --projects project_3 project_4
```

The audit compares generated markdown against source bid markdown and optional human-written construction-organization references. It reports:

- generated/human word-count ratio;
- generated heading count and human-reference heading coverage;
- high-value source fact absorption for numbers, units, dates, parameters, and standards;
- common construction-organization topic coverage;
- actionable issues for outline repair, subsection expansion, evidence utilization, or regeneration.

This quality audit is a stage-level gate. Low heading coverage should feed back into outline repair and source-derived subsection proposals; low source fact absorption should feed into `required_source_facts` and revision-context regeneration.

## Pipeline Stage Gate Report

`application/pipeline_stage_gates.py` provides a read-only gate evaluator for the full generation pipeline. It does not call the LLM and does not mutate project state. The report is exposed through:

```text
GET /projects/{project_id}/pipeline-gates
```

The evaluator summarizes these reusable gates:

1. `input`: source markdown, section files, `toc.json`, and `toc.md`.
2. `profile`: project profile completeness and fallback/extraction-failure markers.
3. `outline`: loaded template tree and project-editable outline nodes.
4. `coverage`: common construction-organization topics from the source TOC against outline nodes.
5. `detail`: target word count, detail level, source/evidence budgets, and split decisions.
6. `mapping`: per-chapter source mappings and no-source routing.
7. `generation`: chapter task status and failed/pending chapters.
8. `revision`: persisted revision decisions and unresolved repair/remap/regenerate/human-input actions.
9. `quality_feedback`: post-generation quality-audit actions that should affect the next pass.
10. `version`: selected chapter versions for final merge.
11. `merge`: final merged markdown availability.

This closes a UI and orchestration gap: the frontend can show a project-level checklist, and future automation can decide whether to run outline repair, source remapping, regeneration, human-input collection, or merge without coupling those decisions directly to FastAPI route code.

## Pipeline Action Plan

`application/pipeline_action_plan.py` is the reusable action adapter above the read-only gate report. It converts gate status plus persisted revision decisions into concrete next actions that a UI, CLI, or background runner can execute.

The action plan is exposed through:

```text
GET /projects/{project_id}/pipeline-actions
```

Each action records:

- `action_id`: stable key for deduplication and frontend display.
- `stage`: pipeline stage such as `coverage`, `detail`, `mapping`, `generation`, `revision`, `version`, or `merge`.
- `action`: executable intent, for example `propose_outline_repair`, `propose_subsections`, `generate_chapters`, `regenerate`, `remap_sources`, or `merge_final`.
- `priority`: `critical / high / normal / low`.
- `endpoint` and `method`: suggested API call when the action can be executed directly.
- `requires_llm`: whether the action will call a model.
- `requires_user_confirmation`: whether the action should create a proposal or ask the user before changing project state.
- `source_gate` or `source_decision`: the gate or revision decision that caused the action.

Quality feedback is also translated into actions:

- `quality_feedback.apply_audit_report`: after generation, prompt the user or automation to submit a quality audit report and optional trace diagnostics.
- `quality_feedback.outline_repair_proposal`: convert stored human-reference heading gaps into editable outline proposal nodes.
- `quality_feedback.remap_and_regenerate`: rerun source mapping and chapter generation with stored trace/audit feedback context, including `not_prompted` facts as mapping hints and supported `prompted_but_omitted` facts as required generation facts.
- `quality_feedback.review_detail_budget`: remind the user to inspect feedback-adjusted word budgets before regenerating.

This layer is deliberately decoupled:

1. `pipeline_stage_gates` diagnoses state.
2. `revision_decision` diagnoses per-chapter draft problems.
3. `pipeline_action_plan` translates those diagnoses into next steps.
4. API routes and frontend components only display or execute the suggested actions; they do not need to reimplement generation-control rules.

Typical mappings:

- `coverage=warning` -> create an outline repair proposal so missing source topics become editable directory nodes.
- `detail=warning` with `split_required_count>0` -> estimate word counts and create subsection proposals for dense craft chapters.
- `mapping=pending/warning` -> run source mapping before factual generation.
- `generation=pending/warning/blocked` -> generate or repair failed chapters.
- unresolved `revision_decisions` such as `regenerate`, `remap_sources`, or `repair_format` -> expose chapter-level actions that carry revision context into the next prompt.
- `version=warning` with missing or weak source-linked generated subsections -> review the selected version content tree before merge.
- `merge=pending` and all previous gates passed -> merge selected chapter versions into final markdown.

This makes “何时需要 LLM 补充修订” operational rather than advisory: the gate and revision rules decide the trigger, the action plan tells the user or automation which endpoint to run, and every action remains traceable to the gate or decision that produced it.

## Iteration Plan

`application/iteration_plan.py` is the user-facing orchestration layer above `pipeline_action_plan`. It does not diagnose new problems and does not call the LLM. Instead, it groups existing gate actions, revision decisions, and quality-feedback actions into ordered phases that a frontend, CLI, or future task runner can follow.

The plan is exposed through:

```text
GET /projects/{project_id}/iteration-plan
```

It persists:

- `control/iteration_plan.json`
- `control/iteration_plan.md`

The phases are stable across project types:

1. `input_profile`: source Markdown, section index, TOC, and project profile.
2. `outline_detail`: editable outline repair, source-derived subsection expansion, and word-count/detail budget.
3. `mapping_generation`: source mapping, evidence extraction, chapter generation, and validation.
4. `revision`: per-chapter actions from revision decisions.
5. `quality_feedback`: audit-driven outline repair, evidence remapping, detail-budget updates, and regeneration context.
6. `version_review`: selected-version evidence audits, generated subsection revision plans, local writing-pattern metadata, and version selection.
7. `version_merge`: final merge of validated selected versions only.

This closes the loop between diagnosis and execution. `pipeline_stage_gates` answers "what is wrong", `pipeline_action_plan` answers "which concrete actions exist", and `iteration_plan` answers "in which order should a user or runner execute those actions, and where must it pause for confirmation before LLM regeneration".

## Quality Feedback Control

The quality audit is intentionally read-only. It detects whether the generated result is too short, misses human-reference headings, omits high-value source facts, or lacks common construction-organization topic groups.

`POST /projects/{project_id}/quality-audit` now runs the same audit from persisted project state. It uses `artifacts/final.md` when the final merge exists, otherwise it merges selected chapter versions in memory and audits that draft. The endpoint persists `control/quality_audit_report.json` and `control/quality_audit_report.md`; with `apply_feedback=true`, it immediately feeds the report into the quality-feedback adapter.

`GET /projects/{project_id}/quality-audit/revision-targets` is the routing layer between report metrics and execution. It converts missing headings, omitted source facts, detail-budget signals, and missing common topics into concrete targets:

- `outline` targets create or review outline proposals before factual writing.
- `chapter` targets remap or regenerate a selected chapter version.
- `content_node` targets rewrite a generated subsection through the existing content-node revision action.
- `detail_budget` targets ask the user to review adjusted word-count budgets before regeneration.

The targets are executable through `POST /projects/{project_id}/quality-audit/revision-targets/{target_index}/execute` or in bounded batches through `POST /projects/{project_id}/quality-audit/revision-targets/execute`. Batch execution skips user-confirmation targets by default, so automatic runs can regenerate source-backed chapters/subsections without silently changing the user-editable outline.

`POST /projects/{project_id}/quality-iteration` wraps the loop into one reusable pipeline step: audit, target planning, bounded target execution, and final re-audit. It persists `control/quality_iteration.json` and `control/quality_iteration.md`, giving project_3/project_4 style real runs a stable comparison artifact across iterations.

The same endpoint also emits a reviewable learning report:

- `control/quality_iteration_learning.json`
- `control/quality_iteration_learning.md`

`GET /projects/{project_id}/quality-iteration/learning-report` rebuilds or reads this report from the latest iteration, then merges the current selected-version `content_revision_targets` and generation-metadata targets before learning. This keeps old or partial `quality_iteration.json` files from hiding newly detected subsection repairs. The report converts repeated omitted source facts, missing human-reference headings, and regeneration/rewrite targets into pattern-library suggestions such as `strengthen_required_source_facts`, `add_revision_signal`, `add_outline_guidance`, and `increase_detail_or_split`. It deliberately does not update `writing_patterns.json` directly. The suggestions are a review layer between real project failures and the reusable local construction-organization skill, so a future pattern refresh can be audited before changing generation behavior.

`POST /pattern-library/learn-from-quality-iteration` consumes that learning report and writes a candidate `writing_patterns.learning.generated.json`. This keeps the feedback loop decoupled: project quality iteration measures failures, pattern learning prepares a candidate skill update, and `POST /pattern-library/apply-generated` remains the explicit human-approved step that changes the active writing skill.

`application/quality_feedback.py` is the reusable control adapter that turns those audit findings into the next run's controls:

- `QualityFeedbackPlan.actions` records normalized action keys, metrics, missing headings, omitted facts, and next steps.
- `policy_adjustments` can increase `target_word_count`, promote detail level, increase source/evidence budgets, or preserve subsection splitting.
- `revision_triggers` route the next pass to `expand_subsections`, `regenerate`, or other existing revision actions instead of relying on manual interpretation of the report.
- CLI tools now persist `{project}_quality_feedback_plan.json` and `{project}_quality_feedback_plan.md` next to the audit report so the next generation run can reuse the same evidence.
- `POST /projects/{project_id}/quality-feedback/outline-proposal` turns missing human-reference headings into editable outline proposal nodes; applying the proposal is still a user-confirmed step.
- Source mapping receives a bounded `Quality Feedback Mapping Requirements` block from the stored feedback plan. `not_prompted` trace facts become source-search requirements before chapter writing starts.
- Chapter generation appends a bounded `Quality Audit Feedback Requirements` prompt block. Missing headings become coverage reminders, and omitted source facts become retry hints that must be verified against mapped source sections before they are written as factual text.
- After source mapping, the pipeline filters quality-feedback omitted facts against the current chapter's selected source sections and evidence spans. Supported facts are injected as `quality_feedback_required_facts`; the evidence-utilization gate marks the chapter `needs_repair` if they are neither written into `## 生成正文` nor explained under `## 人工补充需补充`.

This keeps the control loop decoupled:

1. generation produces traceable markdown;
2. quality audit measures the result;
3. quality feedback converts measurements into actions;
4. outline planning receives proposal nodes for user review;
5. source mapping, evidence extraction, and chapter generation consume the adjusted budgets plus mapping/generation quality-feedback contexts in the next iteration.

## Writing Pattern Matches In Control Plan

The local construction-organization pattern library is no longer only prompt decoration. `writing_pattern_library.match_patterns_for_text()` scores template-node titles and four-module text against the stable local corpus patterns. `GenerationControlPlan.chapter_policies` now persists:

- `writing_pattern_key`: the primary local writing pattern.
- `writing_pattern_matches`: additional matched patterns for mixed chapters.
- `pattern_required_source_facts`: fact types the pattern expects the generation stage to absorb from evidence.
- `pattern_prompt_cards`: structured local-corpus writing requirements used by source mapping, detail design, generation, and revision audits.

During single-chapter generation, the draft metadata is audited immediately. If the primary prompt card is almost entirely omitted and the suggested action is `regenerate`, the draft is marked `needs_repair` before it can become a selected merge candidate. Secondary prompt-card gaps, subsection expansion, and human-input items remain in `generation_metadata_audit` for the readiness/version-review loop, so mixed chapters are not blindly regenerated just because a non-primary pattern has partial coverage.

`generation-readiness` also consumes selected-version generation-metadata targets. A chapter that already has a selected passed version is no longer treated as `ready_for_merge` when its local writing-pattern audit still requires `regenerate`, `expand_subsections`, or human input. Those targets become ordinary readiness revision decisions, so the frontend and batch scheduler can show whether the next step is automatic regeneration, subsection expansion proposal, or user supplement collection.
- `pattern_human_only_items`: fact types that must stay as human-confirmed placeholders unless source or user supplements support them.

These fields are written into `control/generation_control_plan.json/md`, so the frontend and trace review can explain why a chapter is treated as craft, quality, safety, deployment, environment, schedule/resource, or overview. The chapter prompt injects both the primary pattern and matched pattern rules. The pattern library remains a writing-skill layer only: it supplies structure, control points, and quality expectations, not project facts.

## Pattern-Aware Revision Gate

Revision decisions now consume the pattern fields from `ChapterGenerationPolicy`. If a chapter has mapped source sections but the evidence extractor finds no usable `required_source_facts` for a matched local writing pattern, the decision is `remap_sources` instead of `accept`.

This catches the common failure mode where a chapter is formally valid but too generic for its type, for example:

- craft chapters with no construction object, quantity, procedure, or control parameter evidence;
- overview chapters with no scope, location, quantity, schedule, or target facts;
- management chapters with no target, responsibility, inspection, risk, or control evidence.

The next generation attempt receives this decision as revision context. It must re-run mapping/evidence extraction with pattern requirements as hints, or keep unsupported items as human-fill placeholders. The LLM is not allowed to fabricate missing pattern facts simply because the pattern expects them.

## Revision-Aware Source Mapping

`remap_sources`, `regenerate`, and `repair_format` retries now feed their revision context into the source-mapping stage before chapter writing. The mapping prompt receives a `Mapping Control Context` block containing:

- the matched local writing pattern and pattern-required source fact types;
- pattern human-only items that should be searched for but not invented;
- source-derived subtopics and required subtopics;
- previous revision reasons, missing evidence, omitted required facts, and required changes.

The fallback keyword mapper also uses this context as search terms. This closes the loop: a remap decision changes the next source selection/evidence extraction pass instead of only changing the final prose prompt.

## Evidence Utilization Gate

Chapter validation now has a second gate after the Markdown format contract. A chapter can be structurally valid but still be blocked from merge when mapped source evidence is not actually absorbed into `## 生成正文`.

Reusable rule:

1. `source_evidence` extracts evidence spans from mapped source sections.
2. `evidence_utilization.extract_required_source_facts()` derives high-value facts such as numbers, units, dates, standards, quantities, parameters, and method control points.
3. `generate_chapter()` runs `audit_evidence_utilization()` immediately after format validation.
4. If the audit finds omitted required facts, low high-value evidence usage, or explicit manual placeholders that already have source support, the draft status becomes `needs_repair` and the task is not marked `passed`.
5. `revision_decision` converts that audit into `regenerate` or `remap_sources`, with concrete `required_changes` and omitted fact details.
6. `merge_chapters()` only merges drafts whose `validation_status == passed`; a draft file alone is not enough.

This addresses the trace failure mode where a standard, quantity, or parameter appears in the prompt but disappears from the generated body. The model may still decide a fact is out of scope, but it must explain that under `## 人工补充需补充` instead of silently dropping it.

## Trace Evidence Diagnostics

`application/trace_evidence_diagnostics.py` makes the post-generation evidence review actionable instead of anecdotal. It consumes:

- a `quality_audit` report containing `source_facts.omitted_examples`;
- a directory of persisted LLM trace JSON files with `prompt` and `response`.

For each omitted fact it records:

- whether the fact appeared in any prompt;
- whether the fact appeared in any response;
- sample trace files and title hints;
- a suggested control action.

The action split is deliberately simple:

- `not_prompted` -> `remap_sources`: the fact was lost before generation, so source mapping, evidence extraction, or budgets need repair.
- `prompted_but_omitted` -> `regenerate`: the fact reached the model, so the next prompt must carry it as a required source fact and validation should fail if it is silently dropped again.
- `absorbed_in_response` -> `accept` or inspect merge/final-audit scope: the response did contain the fact, so the mismatch may be from final merge selection, deduping, or document-scope audit heuristics.

CLI:

```powershell
$env:PYTHONPATH='src'
python tools\diagnose_trace_evidence.py --quality-report <project_quality_audit.json> --trace-dir <llm-traces-dir>
```

This diagnostic sits between quality audit and quality feedback. It explains whether `strengthen_evidence_utilization` should mostly adjust source mapping or chapter regeneration.

When the diagnostic is supplied to `build_quality_feedback_plan(..., trace_diagnostics=...)` or `POST /projects/{project_id}/quality-feedback`, it becomes control data:

- `not_prompted` facts create a `remap_sources` revision trigger.
- `prompted_but_omitted` facts create a `regenerate` revision trigger.
- `not_prompted` fact labels are rendered into the next source-mapping prompt, forcing the mapper to find supporting sections or return `missing_evidence`.
- source-supported trace fact labels are injected into the next chapter prompt as `quality_feedback_required_facts` and audited after generation.
- `trace_revision_context` separates trace feedback into mapping requirements and generation requirements: `not_prompted` facts stay in source-remap context until the current chapter's selected source text supports them; `prompted_but_omitted` facts become required generation facts when source-supported.

## Batch Source-Derived Subsection Proposal

The control layer now supports project-level subsection expansion before chapter generation:

- `GenerationControlPlan.chapter_policies[].split_required` marks dense chapters that should not be generated as one large block.
- `source_subtopics` are derived from the real input TOC when available; otherwise the local writing-pattern fallback supplies safe generic subtopics.
- `build_project_subsection_proposal_nodes()` scans all split-required chapters and creates one outline proposal containing child nodes for each parent.
- `POST /projects/{project_id}/outline/subsection-proposals` exposes that batch proposal to the UI.
- Applying the proposal is still user-confirmed through the existing outline proposal apply endpoint.

This makes directory-tree generation iterative and reusable: first create or edit the project outline, then batch-expand dense chapters into source-backed leaves, then map sources and generate each leaf independently.

## Layered Outline Planning

`TemplateOutlinePlan.generation_steps` converts a planned outline into execution groups:

- `POST /projects/{project_id}/directory` creates a `template` source plan by default, so even the initial editable directory has deterministic layer steps;
- later AI outline proposals can produce an `ai_plan`, but applying a proposal is still user-confirmed;
- root or parent-level nodes are grouped by `level` and `parent_node_id`;
- each step records the generated `node_ids` and their valid `source_section_ids`;
- `outline/generated_outline.md` renders a “分层生成步骤” section for human review;
- the scheduler can use these steps to generate or audit directory levels before descending into child nodes.

This keeps outline planning decoupled from LLM output shape. The LLM still returns `nodes`, while the application layer derives deterministic layer steps from the validated template tree.

`GET /projects/{project_id}/outline-generation-steps` turns those static groups into a live progress index. For each layer step it reports task status, mapped source ids, selected version id, content-revision action counts, and generation-metadata audit counts. The endpoint writes `control/outline_generation_step_progress.json`, giving both the frontend and a future runner a stable way to execute or review the outline tree layer by layer without recomputing status rules in the UI.

`POST /projects/{project_id}/outline-generation-steps/{step_id}/generate` is the corresponding execution primitive. It does not invent a separate generation path; each node in the selected layer calls the existing single-chapter pipeline, so source mapping, evidence extraction, detail policy, user supplements, local writing patterns, validation, trace files, and version creation stay consistent. Nodes without a generation contract are skipped and recorded, which keeps parent/container headings from becoming unsupported factual text.

`pipeline-actions` promotes the same primitive into the project-level next-action list. When the generation gate is pending or warning and a directory layer has concrete leaf nodes without selected versions, the plan emits `generation.outline_step.{step_id}` with `target_step_id`, `action=generate_outline_step`, and a concrete POST endpoint. The generic `/generate` action remains as a fallback, but the UI can now advance generation layer by layer and keep review decisions attached to the exact outline level that produced them.

Selected chapter versions now persist their `EvidenceUtilizationAudit` beside the content tree and generation metadata. The artifact pair is `chapters/{node_id}/versions/{version_id}.evidence_audit.json` and `.evidence_audit.md`, and the API exposes it through `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit`. This makes source-fact absorption a durable version property instead of a transient validation detail. The version gate counts missing evidence audits and actionable evidence-utilization issues; `pipeline-actions` emits `version.review_evidence_utilization.{node_id}.{version_id}` so the frontend can guide the user to regenerate, remap, or supplement the exact selected version that lost source facts.

The evidence-utilization action is executable through `POST /projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit/revision-action`. It converts the audit into revision context containing omitted `required_source_facts`, unused high-value evidence ids, feedback-required facts, and manual-fill items already supported by source evidence. Regeneration then uses the normal single-chapter path, so source mapping, evidence extraction, prompt traces, validation, version creation, and the next evidence audit remain consistent. This satisfies the retry rule: a failed evidence-absorption pass must carry the concrete omitted facts into the next prompt instead of repeating the previous run.

## Policy-Aware Chapter Prompt

`ChapterGenerationPolicy` is now injected into both source mapping and final chapter generation. This prevents the control layer from calculating detail decisions that the writing stage never sees.

The chapter prompt receives:

- `detail_level`, `split_required`, source/evidence budgets;
- `source_subtopics` derived from the real input TOC;
- `required_subtopics` from reusable construction-organization patterns;
- `writing_pattern_key` and matched local corpus pattern keys;
- `pattern_required_source_facts` to prioritize evidence absorption;
- `pattern_human_only_items` that must remain placeholders unless source evidence or user supplements support them.

The generated正文 still keeps the same Markdown contract. These policy fields are writing controls, not project facts: they decide how deeply and in what internal order to expand the chapter, while quantities, parameters, dates, standards, approvals, coordinates, and conclusions must still come from mapped `section_id/evidence_id`, user supplements, or explicit human-fill placeholders.

The local pattern library also renders a `WritingPatternPromptCard` for each matched pattern. The card is phase-aware:

- `outline_guidance` helps choose or propose outline nodes and source-derived subchapters.
- `source_mapping_requirements` turns expected fact types into source-search requirements.
- `detail_design_rules` allocates target word count across an internal writing order.
- `generation_moves` guides prose organization under the fixed chapter Markdown contract.
- `human_only_items` and `revision_checks` define placeholders and post-generation repair signals.

These cards are structural writing controls only. They are never treated as project factual evidence.
