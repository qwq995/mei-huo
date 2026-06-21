# 小章节生成的原文文段映射方案

## 目标

生成施工组织设计小章节时，LLM 不能只知道“相关章节是哪几个”，还要知道“模板中的哪些要求对应投标文档中的哪些原文段落”。本方案将来源链路拆成两层：

1. 章节级来源映射：由结构化 LLM 从投标目录中选择相关 `section_id`。
2. 文段级证据映射：由后端从已选章节全文中切出段落、表格块和列表块，按模板标题与四模块关键词打分，形成可追溯 evidence map。

最终章节生成 prompt 同时包含：

- 项目概况。
- 当前目录节点四模块。
- 已匹配来源章节摘要。
- 原文文段映射表。
- 已确认来源章节全文。
- 用户补充材料、附件说明、当前选中历史版本。

## 数据结构

`SourceMappingResult` 增强后包含：

- `matches`：章节级匹配结果。
- `matches[].evidence_ids`：该章节下被选中的证据文段 ID。
- `evidence`：文段级证据数组。
- `artifact_path`：完整 JSON 映射文件。
- `evidence_artifact_path`：便于人工查看的 Markdown 证据表。

单条 `SourceEvidenceSpan` 包含：

- `evidence_id`
- `section_id`
- `title_path`
- `start_line`
- `end_line`
- `usage`
- `template_module`
- `matched_terms`
- `quote`
- `summary`
- `reason`
- `confidence`

## 处理流程

1. `map_chapter_sources` 调用结构化 LLM，只选择相关来源章节。
2. `_clean_mapping` 清理不存在的 `section_id`、重复匹配和置信度范围。
3. `source_evidence.build_source_evidence` 对已选章节做文段切片：
   - 空行分段。
   - Markdown 表格连续行作为一个块。
   - 列表连续行作为一个块。
   - 超长段落按句号、分号等断句。
4. 后端按当前模板节点打分：
   - 节点标题。
   - `[主要来源]`。
   - `[自动补充]`。
   - `[人工补充需补充]`。
   - `[特殊备注]`。
5. 每个来源章节保留若干高分 evidence，回填 `evidence_ids`。
6. 写入：
   - `mapping/{node_id}.json`
   - `mapping/{node_id}.evidence.md`
7. `generate_chapter.build_chapter_prompt` 将“原文文段映射表”置于全文来源之前，要求 LLM 优先依据 evidence map 生成。

## Prompt 约束

章节生成 prompt 增加以下约束：

- 优先依据“原文文段映射表”组织正文。
- 涉及项目事实、工程量、工艺参数、质量安全要求时，应从 `evidence_id` 对应原文摘录中取材。
- `## 主要来源摘要` 中优先写出 `evidence_id`、`section_id`、标题路径和依据摘要。
- 不能确定的信息必须保留 `【需人工补充：...】`。

修复 prompt 也带入同一份 evidence map，避免格式修复阶段丢失来源约束。

## 接口与追溯

章节接口返回：

- `source_matches`：章节级摘要。
- `source_mapping.matches`：章节级结构化匹配。
- `source_mapping.evidence`：文段级证据。

本地 artifact：

- `mapping/{node_id}.json`：机器可读完整映射。
- `mapping/{node_id}.evidence.md`：人工可读证据表。
- `runs/{run_id}/validation.json`：包含 `evidence_count` 和 `evidence_artifact_path`。

## 后续增强

- 将 evidence map 在前端章节工作区中做可折叠展示。
- 支持用户手动锁定/排除某条 evidence。
- 真实 LLM 来源映射阶段可先返回候选 section，再由后端 evidence 评分控制实际 prompt 内容，减少模型幻觉。
- 后续接入向量检索时，仍保留本 evidence 数据结构，只替换候选段落评分器。
