# CoalPlan AI 工作台接口文档（流水线版）

默认后端地址：`http://127.0.0.1:8010`  
Swagger：`http://127.0.0.1:8010/docs`

本工作台按“模板选择 -> 投标输入 -> 切章目录 -> 项目目录 -> 字数控制 -> 逐章生成 -> 版本审阅 -> 合并交付”的流水线组织。质量门禁主要用于给出下一步建议，最终是否保留、修改、重生成由用户决定。

## 1. 模板与项目

### `GET /templates`

列出本地模板陈列，用于前端模板选择。

### `GET /templates/{template_id}`

查看模板目录树与四模块配置。常用模板包括：

- `coal_fire`：煤火治理施工组织设计模板
- `hydro_diversion_slope`：水电泄洪/边坡类施工组织设计模板

### `POST /projects`

创建项目。

```json
{
  "name": "拉哇水电演示项目",
  "template_id": "hydro_diversion_slope"
}
```

### `GET /projects`

分页/列表查看项目。

### `GET /projects/{project_id}`

查看项目摘要，包括模板、输入文档数量、切章数量、生成次数。

### `DELETE /projects/{project_id}?keep_artifacts=true`

删除项目数据库记录。`keep_artifacts=true` 时保留本地落盘文件。

## 2. 投标输入与来源目录

### `POST /projects/{project_id}/bid-markdown`

上传投标技术文件 Markdown。后端会规范化、切章、生成来源目录并持久化。

```json
{
  "file_name": "bid.md",
  "content": "# 投标技术文件\n\n## 工程概况\n..."
}
```

落盘产物：

- `inputs/bid.md`
- `inputs/bid.normalized.md`
- `inputs/sections/*.md`
- `inputs/sections.json`
- `inputs/toc.json`
- `inputs/toc.md`

### `POST /projects/{project_id}/normalize`

兼容接口。当前上传 Markdown 后已经自动完成规范化和切章。

### `GET /projects/{project_id}/source-toc`

查看输入文档切章目录。每个条目包含 `section_id`、`title_path`、`level`、`char_count`、`snippet`。

### `GET /projects/{project_id}/sections/{section_id}`

查看某个来源章节全文，供追溯来源、人工审阅和调试提示词。

## 3. 项目目录与生成前控制

### `POST /projects/{project_id}/directory`

生成项目基础目录：抽取项目概况、复制模板为项目可编辑目录、创建章节任务。

### `GET /projects/{project_id}/template-tree`

查看当前项目使用的模板树。

### `GET /projects/{project_id}/outline-nodes`

查看项目可编辑目录。前端目录树以这里为准，而不是直接读取模板。

### `POST /projects/{project_id}/outline-nodes`

新增目录节点。

### `PATCH /projects/{project_id}/outline-nodes/{node_id}`

修改目录节点，可更新标题、父节点、排序、启用状态、目标字数和四模块：

- `source_rules`：主要来源
- `auto_fill`：自动补充
- `manual_fill`：人工补充需补充
- `special_notes`：特殊备注

### `DELETE /projects/{project_id}/outline-nodes/{node_id}`

删除目录节点。

### `POST /projects/{project_id}/outline/pre-generation-refine`

生成前目录精修建议。只创建 proposal，不直接覆盖用户目录。

```json
{
  "mode": "balanced",
  "use_local_corpus": true,
  "use_human_reference": false,
  "project_type": "auto"
}
```

### `POST /projects/{project_id}/outline/proposals/{proposal_id}/apply`

确认并应用目录 proposal。应用后目录节点和章节任务同步更新。

### `POST /projects/{project_id}/outline/word-counts/estimate`

依据参考施组或目录结构估算各章节目标字数。用户可随后手动修改。

## 4. 流水线状态与下一步建议

### `GET /projects/{project_id}/pipeline-blueprint`

查看系统内置的生成流水线定义，适合前端展示“总体流程”。

### `GET /projects/{project_id}/pipeline-actions`

查看当前项目建议动作列表，包括目录修补、拆小节、生成、修订、人工补充等。

### `GET /projects/{project_id}/generation-readiness`

查看每个目录节点是否可生成、是否需拆分、是否需人工补充、是否已有选中版本。

### `POST /projects/{project_id}/generation-readiness/execute`

批量执行 readiness 中可自动执行的动作。默认跳过需要人工确认的事项。

```json
{
  "group_id": null,
  "include_user_confirmation": false,
  "limit": 10
}
```

### `GET /projects/{project_id}/current-execution-window`

查看当前最应该处理的流水线窗口。若存在待确认 proposal，会优先提示用户审阅。

## 5. 章节工作区、补充材料与附件

### `GET /projects/{project_id}/chapters/{node_id}/workspace`

查看单章工作区：目录节点、补充材料、附件、版本、选中版本和待确认 proposal。

### `POST /projects/{project_id}/chapters/{node_id}/supplements`

保存章节补充材料。刷新页面后仍保留。

```json
{
  "kind": "text",
  "title": "现场补充要求",
  "content": "本章需强调高原冬季施工组织。",
  "must_include": true
}
```

### `PATCH /projects/{project_id}/chapters/{node_id}/supplements/{supplement_id}`

修改补充材料。

### `DELETE /projects/{project_id}/chapters/{node_id}/supplements/{supplement_id}`

删除补充材料。

### `POST /projects/{project_id}/chapters/{node_id}/attachments`

上传附件并保存说明。第一版不做图片视觉理解，只把附件说明和文件引用带入 prompt。

## 6. 逐章生成与版本管理

### `POST /projects/{project_id}/chapters/{node_id}/generate`

生成单章新版本。流程为：来源映射 -> 证据抽取 -> 构造 prompt -> LLM 生成 -> 格式/来源审计 -> 保存版本。

### `POST /projects/{project_id}/chapters/{node_id}/children/generate`

生成某个父节点下的子章节，适合目录扩细后的分支生成。

### `POST /projects/{project_id}/chapters/{node_id}/versions`

用户手动保存 Markdown 为新版本，不覆盖旧版本。

### `GET /projects/{project_id}/chapters/{node_id}/versions`

查看章节版本列表。

### `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}`

查看指定章节版本。

### `PATCH /projects/{project_id}/chapters/{node_id}/selected-version`

选择用于最终合并的版本。

```json
{
  "version_id": "ver_xxx"
}
```

### `POST /projects/{project_id}/chapters/{node_id}/propose-ai-edit`

根据用户建议生成 AI 修改 proposal，不直接覆盖版本。

### `POST /projects/{project_id}/chapters/{node_id}/proposals/{proposal_id}/apply`

确认 AI 修改 proposal，并保存为新章节版本。

## 7. 正文小节树与审计

### `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-tree`

查看生成正文被拆分后的内容树。用户可按小节审阅来源映射和修改建议。

### `POST /projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-nodes/{content_node_id}/revision-action`

对正文小节执行修订动作，例如重写小节、重新映射来源、拆分小节或请求人工补充。

### `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}/generation-metadata`

查看生成元数据与本地施组写作模式吸收情况。

### `POST /projects/{project_id}/chapters/{node_id}/versions/{version_id}/generation-metadata/revision-action`

依据生成元数据执行建议动作。门控是建议，不替代用户选择。

### `GET /projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit`

查看证据利用审计，包括遗漏的高价值事实、未使用证据和建议动作。

### `POST /projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit/revision-action`

依据证据审计执行修订动作。

## 8. 合并与导出

### `POST /projects/{project_id}/merge`

合并所有用户选中的章节版本，生成最终 Markdown。未选中版本不会进入合并。

### `GET /projects/{project_id}/artifacts/final.md`

查看最终 Markdown。

## 9. 前端推荐展示

前端首页应把状态浓缩成流水线卡片：

1. 模板与项目：是否已选模板、是否创建项目。
2. 投标输入：是否上传 Markdown、切章数量。
3. 目录精修：项目目录节点数、待确认 proposal。
4. 字数控制：已设置目标字数的节点数与总目标字数。
5. 生成准备：readiness 状态、可自动执行批次、需人工确认数量。
6. 逐章生成：已选中版本的章节数、当前章节版本数。
7. 审计修订：证据/组织模式审计是否提示修订。
8. 合并交付：是否已生成 final.md。

## 10. 运行约定

- 事实只能来自输入文档 `section_id/evidence_id`、用户补充或人工占位。
- 本地施组目录库只作结构参考，不作项目事实来源。
- 质量门禁用于提示下一步，不应强制替用户决定最终质量。
- 每次 LLM 调用应保存 prompt/response trace，便于追溯。
- 章节 AI 生成、AI 修改、用户手动编辑都创建新版本。
