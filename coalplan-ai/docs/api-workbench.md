# CoalPlan AI 工作台接口文档

本文档对应当前 FastAPI 后端。默认服务地址为 `http://127.0.0.1:8010`，交互式 Swagger 为 `http://127.0.0.1:8010/docs`。

## 基本约定

- `project_id`：项目 ID，创建项目后由后端返回。
- `node_id`：项目目录节点 ID，来自 `GET /projects/{project_id}/outline-nodes`。
- `section_id`：输入投标 Markdown 切分后的来源章节 ID。
- 第一阶段核心输入为 Markdown；DOCX/PDF 转 Markdown 属于前置工具流程。
- 大文件、章节产物、prompt trace 等落盘到 artifact 目录；项目、目录、补充材料、附件记录、版本选择等状态进入 SQLite。
- 附件第一版只保存文件和说明，不做视觉识别；生成时会把附件说明和文件引用插入 prompt。

## 1. 模板接口

### `GET /templates`

列出本地模板陈列。

返回示例：

```json
[
  {
    "template_id": "coal_fire",
    "name": "火区治理施工组织设计模板",
    "path": "src/coalplan/assets/templates/coal_fire_template.md"
  }
]
```

### `GET /templates/{template_id}`

查看指定模板目录树和四模块。

主要字段：

- `template_id`
- `name`
- `nodes[]`
  - `id`
  - `title`
  - `level`
  - `source_rules`
  - `auto_fill`
  - `manual_fill`
  - `special_notes`
  - `target_word_count`
  - `children`

### `GET /projects/{project_id}/template-tree`

查看某个项目当前加载的模板树。

## 2. 项目接口

### `POST /projects`

创建项目。

请求：

```json
{
  "name": "宁夏煤火北一火区演示",
  "template_id": "coal_fire"
}
```

返回：

```json
{
  "id": "project_xxx",
  "project_id": "project_xxx",
  "name": "宁夏煤火北一火区演示",
  "template_id": "coal_fire",
  "source_document_count": 0,
  "section_count": 0,
  "run_count": 0
}
```

### `GET /projects`

列出所有未删除项目。

### `GET /projects/{project_id}`

查看项目摘要。

### `DELETE /projects/{project_id}?keep_artifacts=true`

删除数据库中的项目记录。当前 `keep_artifacts` 作为接口参数保留，默认不清理本地 artifact 目录。

### `POST /projects/{project_id}/template`

切换项目模板。

请求：

```json
{
  "template_id": "hydro_diversion_slope"
}
```

## 3. 输入文档与来源目录

### `POST /projects/{project_id}/bid-markdown`

上传投标 Markdown。后端会保存原文、规范化、切分章节、生成来源目录，并持久化到本地 artifact 和数据库。

请求：

```json
{
  "file_name": "bid.md",
  "content": "# 投标技术文件\n\n## 工程概况\n..."
}
```

主要落盘结果：

- `.coalplan-data/artifacts/{project_id}/inputs/bid.md`
- `.coalplan-data/artifacts/{project_id}/inputs/bid.normalized.md`
- `.coalplan-data/artifacts/{project_id}/inputs/sections/*.md`
- `.coalplan-data/artifacts/{project_id}/inputs/sections.json`
- `.coalplan-data/artifacts/{project_id}/inputs/toc.json`
- `.coalplan-data/artifacts/{project_id}/inputs/toc.md`

### `POST /projects/{project_id}/normalize`

兼容接口。当前上传 Markdown 时已自动规范化；该接口只检查项目已有切章。

### `GET /projects/{project_id}/source-toc`

查看输入文档切章目录。

返回：

```json
{
  "items": [
    {
      "section_id": "sec_001",
      "title_path": ["工程概况"],
      "level": 2,
      "start_line": 1,
      "end_line": 20,
      "keywords": [],
      "char_count": 500,
      "snippet": "本项目位于..."
    }
  ],
  "artifact_json_path": ".../toc.json",
  "artifact_markdown_path": ".../toc.md"
}
```

### `GET /projects/{project_id}/sections/{section_id}`

查看单个来源章节全文。

### `POST /projects/{project_id}/directory`

生成基础项目目录、项目概况、项目级可编辑目录节点和章节任务。该接口优先保证“目录可用”，不会因为 AI 目录规划失败而阻塞用户继续编辑。

返回：

```json
{
  "project": {},
  "template": {},
  "source_toc": {},
  "outline": {},
  "chapter_tasks": [],
  "profile_status": "ready",
  "outline_status": "not_run",
  "outline_source": "template",
  "warnings": [
    "已生成基础模板目录。可继续手动编辑，或点击 AI 优化目录生成可确认的修改建议。"
  ]
}
```

字段说明：

- `profile_status`：`ready | not_ready`。
- `outline_status`：`not_run | planned`。
- `outline_source`：`template | ai_plan`。
- `warnings`：给前端展示的用户友好提示。

### `GET /projects/{project_id}/directory`

查看项目目录生成结果、来源目录、模板树和章节任务。

### `GET /projects/{project_id}/profile`

查看项目概况抽取结果。

### `GET /projects/{project_id}/outline`

查看 AI 规划的目录四模块结果。

## 4. 项目目录编辑接口

项目目录生成后会复制到 `project_outline_nodes`，用户编辑的是项目自己的目录，不会修改模板原文件。

### `GET /projects/{project_id}/outline-nodes`

列出项目可编辑目录节点。

### `POST /projects/{project_id}/outline-nodes`

新增目录节点。

请求：

```json
{
  "title": "安全文明施工补充措施",
  "parent_id": "node_abc",
  "level": 3,
  "sort_order": 20,
  "enabled": true,
  "source_rules": ["投标文件安全管理章节"],
  "auto_fill": ["归纳安全管理制度"],
  "manual_fill": ["【需人工补充：现场安全负责人和审批记录。】"],
  "special_notes": [],
  "target_word_count": 800
}
```

### `PATCH /projects/{project_id}/outline-nodes/{node_id}`

修改目录节点。请求体可只传需要修改的字段。

```json
{
  "title": "1.1 工程概况",
  "enabled": true,
  "source_rules": ["工程概况", "治理范围"],
  "auto_fill": ["归纳项目位置、范围和施工内容"],
  "manual_fill": ["【需人工补充：合同工期。】"],
  "special_notes": ["火区边界以复勘成果为准"],
  "target_word_count": 1200
}
```

`target_word_count` 为章节目标字数，可传 `null` 清空。单章生成时会按目标字数控制详略，但仍以真实来源为准，不得为了凑字数编造参数。

### `DELETE /projects/{project_id}/outline-nodes/{node_id}`

删除目录节点。

### `POST /projects/{project_id}/outline/propose-ai-change`

创建目录 AI 修改建议，只生成 proposal，不直接覆盖目录。

请求：

```json
{
  "suggestion": "把安全文明施工拆成安全管理、环保水保、应急处置三个小节。"
}
```

### `POST /projects/{project_id}/outline/ai-plan`

基于项目概况、投标目录和模板树生成 AI 目录优化建议。该接口也只创建 proposal，不直接覆盖当前项目目录。

请求：

```json
{
  "suggestion": "请基于项目概况、投标目录和模板四模块优化项目目录。"
}
```

### `POST /projects/{project_id}/outline/proposals/{proposal_id}/apply`

确认应用目录 proposal。

### `POST /projects/{project_id}/outline/word-counts/estimate`

根据参考施组 Markdown 或章节类型为项目目录批量估算目标字数，并写回项目自己的可编辑目录。

请求：

```json
{
  "reference_markdown": "# 施工组织设计\n\n## 1.1 工程概况\n..."
}
```

返回：

```json
{
  "project_id": "project_xxx",
  "reference_supplied": true,
  "estimates": [
    {
      "node_id": "tplnode_xxx",
      "title": "1.1 工程概况",
      "target_word_count": 1200,
      "method": "reference_title_match",
      "matched_reference_title": "1.1 工程概况",
      "reference_word_count": 1184
    }
  ],
  "nodes": []
}
```

落盘追溯文件：

- `outline/word_count_targets.json`
- `outline/word_count_targets.md`

生成 prompt 会读取该字段，并要求模型在目标字数约 `85%-120%` 范围内控制详略；来源不足时仍必须保留人工补充占位，不得为了凑字数编造参数。

## 5. 章节工作区接口

### `GET /projects/{project_id}/chapters/{node_id}/workspace`

查看某章工作区，包含：

- `outline_node`
- `supplements`
- `attachments`
- `versions`
- `selected_version_id`
- `proposals`

`versions` 中每个版本会附带生成正文目录树：

- `content_tree`：由版本 Markdown 标题解析出的正文树，支持生成后按小节查看、映射与修改。
- `content_tree_path`：对应落盘 JSON artifact 路径。

### `POST /projects/{project_id}/chapters/{node_id}/supplements`

新增章节补充材料。

请求：

```json
{
  "kind": "text",
  "title": "现场补充要求",
  "content": "本章必须写入临时供水布置要求。",
  "must_include": true,
  "sort_order": 1
}
```

`kind` 建议值：

- `text`：普通文本
- `table`：Markdown 表格
- `note`：写作要求或人工说明

### `PATCH /projects/{project_id}/chapters/{node_id}/supplements/{supplement_id}`

修改章节补充材料。

### `DELETE /projects/{project_id}/chapters/{node_id}/supplements/{supplement_id}`

删除章节补充材料。

### `POST /projects/{project_id}/chapters/{node_id}/attachments`

上传章节附件。请求类型为 `multipart/form-data`。

字段：

- `file`：附件文件
- `description`：附件说明

第一版生成时只使用 `description` 和文件路径，不解析图片内容。

### `DELETE /projects/{project_id}/chapters/{node_id}/attachments/{attachment_id}`

删除附件记录。

## 6. 章节生成、版本与正文树接口

### `GET /projects/{project_id}/chapters`

查看当前最新 generation run 的章节任务列表。

### `POST /projects/{project_id}/chapters/{node_id}/generate`

单章生成。流程为：

1. 依据当前目录节点和来源目录做来源映射。
2. 对已匹配章节做后端细粒度证据抽取，生成 `evidence_id / section_id / 标题路径 / 行号范围 / 原文摘录 / 对应模板模块 / 使用方式`。
3. 把“原文文段映射表”和映射到的来源章节全文加入 prompt。
4. 注入项目概况、目录四模块、章节目标字数、章节补充材料、附件说明和当前选中历史版本。
5. LLM 生成 Markdown。
6. 校验格式。
7. 创建新的 `chapter_versions` 版本并设为选中。
8. 从该版本 Markdown 解析生成正文目录树，并保存到 `chapters/{node_id}/versions/{version_id}.content_tree.json`。

落盘追溯文件：

- `mapping/{node_id}.json`：章节级来源映射与文段级 evidence。
- `mapping/{node_id}.evidence.md`：便于人工查看的原文文段映射表。
- `chapters/{node_id}.md`：本次章节生成结果。
- `chapters/{node_id}/versions/{version_id}.content_tree.json`：生成正文目录树，包含正文小节与来源证据映射。

返回：

```json
{
  "node_id": "node_xxx",
  "title": "1.1 工程概况",
  "status": "passed",
  "markdown": "# 1.1 工程概况\n...",
  "draft_path": ".../chapters/node_xxx.md",
  "source_matches": [],
  "source_mapping": {
    "node_id": "node_xxx",
    "matches": [
      {
        "section_id": "sec_xxx",
        "title_path": ["施工组织", "工程概况"],
        "usage": "fact",
        "reason": "与工程概况相关",
        "confidence": 0.86,
        "evidence_ids": ["ev_xxx"]
      }
    ],
    "evidence": [
      {
        "evidence_id": "ev_xxx",
        "section_id": "sec_xxx",
        "start_line": 42,
        "end_line": 44,
        "template_module": "main_sources",
        "quote": "原文摘录..."
      }
    ]
  },
  "version": {}
}
```

### `GET /projects/{project_id}/chapters/{node_id}`

查看单章当前结果。优先返回选中版本；没有选中版本时返回最近 draft。

### `POST /projects/{project_id}/generate`

全量逐章生成。每个章节都会创建版本。

### `POST /projects/{project_id}/merge`

合并最终 Markdown。合并时优先使用每章 `selected_version_id` 对应的版本。

### `GET /projects/{project_id}/artifacts/final.md`

查看最终合并 Markdown，返回 `text/plain`。

### `POST /projects/{project_id}/chapters/{node_id}/versions`

手动保存当前编辑内容为新版本。

请求：

```json
{
  "title": "1.1 工程概况",
  "markdown": "# 1.1 工程概况\n\n## 主要来源摘要\n...",
  "select": true
}
```

### `GET /projects/{project_id}/chapters/{node_id}/versions`

列出某章版本。

### `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}`

查看某章指定版本。

返回版本对象包含：

```json
{
  "id": "ver_xxx",
  "version_no": 1,
  "source_type": "ai_generate",
  "markdown": "# 1.1 工程概况\n...",
  "content_tree_path": "chapters/node_xxx/versions/ver_xxx.content_tree.json",
  "content_tree": {
    "version_id": "ver_xxx",
    "node_id": "node_xxx",
    "title": "1.1 工程概况",
    "nodes": []
  }
}
```

### `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-tree`

查看某个版本的生成正文目录树。目录树由章节 Markdown 标题解析得到，每个小节节点包含：

- `id`：正文小节节点 ID。
- `title / level / title_path`：小节标题与层级路径。
- `start_line / end_line`：该小节在版本 Markdown 中的行号范围。
- `markdown / body`：该小节原始 Markdown 与正文。
- `source_links`：小节映射到的 `section_id / evidence_id`，用于追溯来源。
- `children`：子小节。

### `PATCH /projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-nodes/{content_node_id}`

按生成正文目录树的小节节点修改内容。后端不会覆盖原版本，而是创建一个 `source_type=subsection_edit` 的新版本，并重新生成该新版本的 `content_tree`。

请求：

```json
{
  "markdown": "## 修改后的小节标题\n\n修改后的正文...",
  "select": true
}
```

典型用法：

1. 前端读取 `content-tree` 并展示版本内的小节树。
2. 用户选择某个小节节点，只编辑该节点对应的 Markdown。
3. 调用本接口保存为新版本。
4. 合并最终文档时仍只使用用户选中的版本。

### `PATCH /projects/{project_id}/chapters/{node_id}/selected-version`

选择某个版本作为最终合并使用版本。

请求：

```json
{
  "version_id": "ver_xxx"
}
```

### `POST /projects/{project_id}/chapters/{node_id}/propose-ai-edit`

创建章节 AI 修改建议。只生成 proposal，不直接覆盖版本。

请求：

```json
{
  "suggestion": "补强安全措施，语气更像正式施工组织设计。",
  "base_markdown": "# 1.1 工程概况\n..."
}
```

若不传 `base_markdown`，后端会读取当前选中版本。

### `POST /projects/{project_id}/chapters/{node_id}/proposals/{proposal_id}/apply`

确认应用章节 AI 修改建议。应用后会创建新版本并设为选中。

## 7. 推荐前端流程

1. `GET /templates`：加载模板列表。
2. `POST /projects`：创建项目。
3. `POST /projects/{id}/bid-markdown`：上传标准 Markdown 投标文件。
4. `POST /projects/{id}/directory`：生成基础目录、项目概况和章节任务。
5. `POST /projects/{id}/outline/word-counts/estimate`：按参考施组或章节类型估算目录字数。
6. `GET /projects/{id}/outline-nodes`：展示并允许用户编辑目录、四模块、目标字数和启停状态。
7. `GET /projects/{id}/chapters/{node_id}/workspace`：进入章节工作区。
8. 用户保存补充材料或附件说明。
9. `POST /projects/{id}/chapters/{node_id}/generate`：单章生成，生成后形成版本和正文小节树。
10. `GET /projects/{id}/chapters/{node_id}/versions/{version_id}/content-tree`：查看正文小节树与来源映射。
11. `PATCH /projects/{id}/chapters/{node_id}/versions/{version_id}/content-nodes/{content_node_id}`：按小节编辑并保存为新版本。
12. 用户手动编辑整章时用 `POST /versions` 保存新版本。
13. 用户选择版本时用 `PATCH /selected-version`。
14. 全部章节完成后 `POST /merge`。
15. `GET /artifacts/final.md`：预览最终文档。

## 8. 持久化与追溯位置

默认位置：

```text
C:\Users\Lenovo\Documents\煤火\coalplan-ai\.coalplan-data
```

关键文件：

- `.coalplan-data/coalplan.db`：SQLite 数据库。
- `.coalplan-data/artifacts/{project_id}/inputs/bid.md`：上传原始 Markdown。
- `.coalplan-data/artifacts/{project_id}/inputs/bid.normalized.md`：规范化 Markdown。
- `.coalplan-data/artifacts/{project_id}/inputs/sections/*.md`：切分章节。
- `.coalplan-data/artifacts/{project_id}/inputs/toc.json`：来源目录。
- `.coalplan-data/artifacts/{project_id}/profile/project_profile.json`：项目概况。
- `.coalplan-data/artifacts/{project_id}/outline/generated_outline.json`：目录规划。
- `.coalplan-data/artifacts/{project_id}/outline/word_count_targets.json`：字数估算结果。
- `.coalplan-data/artifacts/{project_id}/mapping/{node_id}.json`：单章来源映射。
- `.coalplan-data/artifacts/{project_id}/mapping/{node_id}.evidence.md`：来源证据摘录表。
- `.coalplan-data/artifacts/{project_id}/chapters/{node_id}.md`：单章生成 Markdown。
- `.coalplan-data/artifacts/{project_id}/chapters/{node_id}/versions/{version_id}.content_tree.json`：正文小节树。
- `.coalplan-data/artifacts/{project_id}/artifacts/final.md`：最终合并 Markdown。
- `.coalplan-data/llm-traces`：LLM prompt/response 追溯记录。
