# CoalPlan AI 工作台接口文档

本文档对应当前 FastAPI 后端。默认服务地址为 `http://127.0.0.1:8010`，交互式 Swagger 为 `http://127.0.0.1:8010/docs`。

## 约定

- `project_id`：项目 ID，创建项目后由后端返回。
- `node_id`：项目目录节点 ID，来自 `GET /projects/{project_id}/outline-nodes`。
- `section_id`：输入投标 Markdown 切分后的来源章节 ID。
- 第一阶段输入文件为 Markdown；DOCX/PDF 转 Markdown 属于前置流程。
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

返回字段：

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

分页能力尚未接入，当前返回全部未删除项目。

### `GET /projects/{project_id}`

查看项目摘要。

### `DELETE /projects/{project_id}?keep_artifacts=true`

删除数据库中的项目记录。当前 `keep_artifacts` 仅作为接口参数保留，默认不清理本地 artifact 目录。

### `POST /projects/{project_id}/template`

切换项目模板。

请求：

```json
{
  "template_id": "hydro_diversion_slope"
}
```

## 3. 输入文档与目录

### `POST /projects/{project_id}/bid-markdown`

上传投标 Markdown。后端会自动保存原文、规范化、切分章节、生成来源目录，并持久化到本地 artifact 和数据库。

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

兼容接口。当前上传 Markdown 时已自动规范化；此接口只检查项目已有切章。

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

生成项目概况、模板化目录规划、项目级可编辑目录节点、章节任务。

返回：

```json
{
  "project": {},
  "template": {},
  "source_toc": {},
  "outline": {},
  "chapter_tasks": []
}
```

### `GET /projects/{project_id}/directory`

查看项目目录生成结果、来源目录、模板树和章节任务。

### `GET /projects/{project_id}/profile`

查看项目概况抽取结果。

### `GET /projects/{project_id}/outline`

查看 AI 规划的目录四模块结果。

## 4. 项目目录编辑接口

项目目录生成后会复制到 `project_outline_nodes`，用户编辑的是项目自己的目录，不会改模板原件。

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
  "manual_fill": ["【需人工补充：现场安全负责人和审批记录】"],
  "special_notes": []
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
  "manual_fill": ["【需人工补充：合同工期】"],
  "special_notes": ["火区边界以复勘成果为准"]
}
```

### `DELETE /projects/{project_id}/outline-nodes/{node_id}`

删除目录节点。

### `POST /projects/{project_id}/outline/propose-ai-change`

创建目录 AI 修改建议，只生成 proposal，不直接覆盖目录。

请求：

```json
{
  "suggestion": "把安全文明施工拆成安全管理、环保水保、应急处置三个小节"
}
```

### `POST /projects/{project_id}/outline/proposals/{proposal_id}/apply`

确认应用目录 proposal。

## 5. 章节工作区接口

### `GET /projects/{project_id}/chapters/{node_id}/workspace`

查看某章工作区，包含：

- `outline_node`
- `supplements`
- `attachments`
- `versions`
- `selected_version_id`
- `proposals`

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

## 6. 章节生成与版本接口

### `GET /projects/{project_id}/chapters`

查看当前最新 generation run 的章节任务列表。

### `POST /projects/{project_id}/chapters/{node_id}/generate`

单章生成。流程为：

1. 依据当前目录节点和来源目录做来源映射。
2. 把映射到的来源章节全文加入 prompt。
3. 注入项目概况、目录四模块、章节补充材料、附件说明、当前选中历史版本。
4. LLM 生成 Markdown。
5. 校验格式。
6. 创建新的 `chapter_versions` 版本并设为选中。

返回：

```json
{
  "node_id": "node_xxx",
  "title": "1.1 工程概况",
  "status": "passed",
  "markdown": "# 1.1 工程概况\n...",
  "draft_path": ".../chapters/node_xxx.md",
  "source_matches": [],
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
3. `POST /projects/{id}/bid-markdown`：上传 Markdown。
4. `POST /projects/{id}/directory`：生成项目目录。
5. `GET /projects/{id}/outline-nodes`：展示并允许用户编辑目录。
6. `GET /projects/{id}/chapters/{node_id}/workspace`：进入章节工作区。
7. 用户保存补充材料或附件。
8. `POST /projects/{id}/chapters/{node_id}/generate`：单章生成。
9. 用户手动编辑后 `POST /versions` 保存新版本。
10. 用户选择版本后 `PATCH /selected-version`。
11. 全部章节完成后 `POST /merge`。
12. `GET /artifacts/final.md`：预览最终文档。
