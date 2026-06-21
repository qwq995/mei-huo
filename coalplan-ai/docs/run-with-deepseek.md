# 使用 DeepSeek 启动前后端

本文档用于本地演示“投标 Markdown 输入 -> 切章目录 -> 可编辑目录 -> 字数估算 -> 章节工作区 -> 逐章生成 -> 正文小节树编辑 -> 版本管理 -> 合并 final.md”的工作台流程。

## 0. 安全说明

不要把真实 API Key 写入仓库文件。建议只在当前 PowerShell 会话中设置环境变量：

```powershell
$env:COALPLAN_DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

如果一定要长期保存，请放到本机私有 `.env.local`，并确认 `.gitignore` 已忽略该文件。

## 1. 项目目录

项目根目录：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai
```

主要目录：

- `src/coalplan`：后端 Python 源码。
- `src/coalplan/web`：前端 React/Vite。
- `src/coalplan/assets/templates`：本地施工组织设计模板。
- `.coalplan-data`：默认 SQLite 与 artifact 存储。
- `.coalplan-data/artifacts/{project_id}`：每个项目的输入、切章、prompt trace、章节、版本正文树和 `final.md`。

## 2. 安装依赖

首次运行或依赖变更后执行：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai
python -m pip install -e .

cd C:\Users\Lenovo\Documents\煤火\coalplan-ai\src\coalplan\web
npm install
```

如果不使用 editable install，也可以运行时设置：

```powershell
$env:PYTHONPATH="src"
```

## 3. DeepSeek 后端启动

在项目根目录打开一个 PowerShell：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai

$env:PYTHONPATH="src"
$env:COALPLAN_STORAGE_DIR=".coalplan-data"
$env:COALPLAN_LLM_PROVIDER="deepseek"
$env:COALPLAN_STRUCTURED_LLM_PROVIDER="deepseek"
$env:COALPLAN_DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:COALPLAN_DEEPSEEK_API_KEY="你的 DeepSeek API Key"
$env:COALPLAN_DEEPSEEK_MODEL="deepseek-v4-pro"
$env:COALPLAN_LLM_TRACE_DIR=".coalplan-data\llm-traces"

python -m uvicorn coalplan.main:app --host 127.0.0.1 --port 8010
```

启动后访问：

- API 根服务：`http://127.0.0.1:8010`
- Swagger：`http://127.0.0.1:8010/docs`
- OpenAPI JSON：`http://127.0.0.1:8010/openapi.json`

字段说明：

- `COALPLAN_STORAGE_DIR`：数据库与 artifact 的根目录。
- `COALPLAN_LLM_PROVIDER=deepseek`：章节正文生成使用 DeepSeek。
- `COALPLAN_STRUCTURED_LLM_PROVIDER=deepseek`：项目概况、目录规划、来源映射等结构化阶段也使用 DeepSeek。
- `COALPLAN_DEEPSEEK_MODEL=deepseek-v4-pro`：具体生成模型。
- `COALPLAN_LLM_TRACE_DIR`：缓存每次 LLM prompt 与 response，便于追溯。

## 4. 前端启动

再打开一个 PowerShell：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai\src\coalplan\web

$env:VITE_COALPLAN_API_BASE="http://127.0.0.1:8010"
npm run dev
```

默认前端地址：

```text
http://127.0.0.1:5174
```

如果 5174 被占用，可指定端口：

```powershell
$env:VITE_COALPLAN_API_BASE="http://127.0.0.1:8010"
npx vite --host 127.0.0.1 --port 5176
```

## 5. 推荐演示流程

1. 打开前端页面。
2. 在左侧选择模板，例如“火区治理施工组织设计模板”或“水电泄洪边坡施工组织设计模板”。
3. 创建项目。
4. 上传标准 Markdown 投标文件。
5. 点击“生成基础目录”。
6. 在“字数目标”区域上传或粘贴目标施组 Markdown，点击“估算字数”。
7. 在项目目录中调整节点标题、四模块、启停状态、排序和目标字数。
8. 进入章节工作区，添加补充材料、Markdown 表格或附件说明。
9. 点击“生成当前章”。
10. 生成后在右侧版本区查看版本，并展开“正文小节树”。
11. 选择某个正文小节，编辑该小节后点击“保存小节为新版本”。
12. 如需整章修改，可直接编辑 Markdown 并“保存为新版本”。
13. 全部章节完成后点击“合并选中版本”。
14. 在底部查看最终合并 Markdown。

## 6. 标准输入文件示例

煤火样例：

```text
C:\Users\Lenovo\Desktop\示例输入输出\project_1\投标文档（md版本）.md
```

水电样例：

```text
C:\Users\Lenovo\Desktop\示例输入输出\project_2\投标文档（md版本）.md
```

参考施组 Markdown 可用于估算目录字数：

```text
C:\Users\Lenovo\Desktop\示例输入输出\project_1\生成文档（包含信息来源）.md
C:\Users\Lenovo\Desktop\示例输入输出\project_2\生成文档（包含信息来源）.md
```

如果要从 DOCX 转换：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai
$env:PYTHONPATH="src"

python tools\docx_to_markdown.py `
  "D:\Task\方案大模型资料\方案大模型资料\1.宁夏煤火\投标文件-商务-技术-报价清单\技术\宁夏贺兰山汝箕沟太西煤火区安全与生态治理项目一期工程北一火区治理施工项目技术文件（2025.6.16）终版.docx" `
  data\real_inputs\ningxia_coal_fire_bid.raw.md

python -m coalplan.interfaces.cli.normalize_markdown `
  data\real_inputs\ningxia_coal_fire_bid.raw.md `
  data\real_inputs\ningxia_coal_fire_bid.normalized.md
```

## 7. 全量真实 DeepSeek 生成脚本

如需用真实 DeepSeek 对两个示例项目跑完整链路：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai

$env:PYTHONPATH="src"
$env:COALPLAN_DEEPSEEK_API_KEY="你的 DeepSeek API Key"
$env:COALPLAN_DEEPSEEK_MODEL="deepseek-v4-pro"

python tools\run_deepseek_full_generation.py
```

脚本会完成：

- 创建隔离存储目录。
- 上传两个项目的标准投标 Markdown。
- 生成目录和项目概况。
- 按参考施组估算各章节目标字数。
- 使用 DeepSeek 逐章生成。
- 保存 prompt/response trace。
- 保存章节版本、正文小节树和最终合并 Markdown。
- 输出汇总报告。

输出目录形如：

```text
.coalplan-deepseek-full-wordcount-YYYYMMDD-HHMMSS
```

关键结果：

- `deepseek_full_generation_summary.json`
- `deepseek_full_generation_report.md`
- `project_1_final.md`
- `project_2_final.md`
- `storage/artifacts/{project_id}/...`

## 8. 本地持久化结果

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
- `.coalplan-data/artifacts/{project_id}/outline/word_count_targets.json`：字数估算。
- `.coalplan-data/artifacts/{project_id}/mapping/{node_id}.json`：单章来源映射。
- `.coalplan-data/artifacts/{project_id}/mapping/{node_id}.evidence.md`：证据摘录。
- `.coalplan-data/artifacts/{project_id}/chapters/{node_id}.md`：单章生成 Markdown。
- `.coalplan-data/artifacts/{project_id}/chapters/{node_id}/versions/{version_id}.content_tree.json`：正文小节树。
- `.coalplan-data/artifacts/{project_id}/artifacts/final.md`：最终合并 Markdown。
- `.coalplan-data/llm-traces`：LLM prompt/response 追溯记录。

数据库保存：

- 项目列表。
- 输入文档元数据。
- 来源章节。
- 项目可编辑目录节点。
- 章节补充材料。
- 章节附件记录。
- 章节多版本。
- 当前选中版本。
- AI 修改建议。
- 生成运行状态。
- LLM trace 元数据。

## 9. 快速健康检查

后端启动后：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/templates
Invoke-RestMethod http://127.0.0.1:8010/projects
```

前端构建检查：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai\src\coalplan\web
npm run build
```

后端测试：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai
$env:PYTHONPATH="src"
$env:PYTHONIOENCODING="utf-8"
python -m compileall -q src tests tools
python -m unittest discover -s tests
```

## 10. 常见问题

### 端口被占用

查看端口：

```powershell
Get-NetTCPConnection -LocalPort 8010
Get-NetTCPConnection -LocalPort 5174
```

改后端端口：

```powershell
python -m uvicorn coalplan.main:app --host 127.0.0.1 --port 8011
```

改前端 API 地址：

```powershell
$env:VITE_COALPLAN_API_BASE="http://127.0.0.1:8011"
npx vite --host 127.0.0.1 --port 5176
```

### 前端显示空项目

确认前端 `VITE_COALPLAN_API_BASE` 指向当前后端端口。

### DeepSeek 没有调用或返回很短

检查：

```powershell
echo $env:COALPLAN_LLM_PROVIDER
echo $env:COALPLAN_DEEPSEEK_MODEL
echo $env:COALPLAN_LLM_TRACE_DIR
```

确认后端是在设置环境变量之后启动的。环境变量改动不会自动影响已经运行的 uvicorn，需要重启后端。

### 生成后想追溯 prompt

查看：

```powershell
Get-ChildItem .coalplan-data\llm-traces -Recurse
```

或查看项目 artifact：

```powershell
Get-ChildItem .coalplan-data\artifacts -Recurse
```

## 11. 不接真实模型的本地演示模式

如果只演示流程，不希望消耗 DeepSeek：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai

$env:PYTHONPATH="src"
$env:COALPLAN_STORAGE_DIR=".coalplan-data"
$env:COALPLAN_LLM_PROVIDER="source_driven"
$env:COALPLAN_STRUCTURED_LLM_PROVIDER="source_driven"

python -m uvicorn coalplan.main:app --host 127.0.0.1 --port 8010
```
