# CoalPlan AI

火区治理施工组织设计 Markdown 生成原型。

第一阶段只处理文本：输入一份火区治理投标技术文件 Markdown，系统先规范化并切分为可检索章节，再生成项目概况、模板目录规划、逐章节来源映射和逐章节施组正文，校验通过后合并为完整施工组织设计 Markdown。

## Pipeline

1. `inputs/bid.md`：保存原始投标 Markdown。
2. `inputs/bid.normalized.md`：规范化标题、目录和正文结构。
3. `inputs/sections/*.md`、`inputs/sections.json`、`inputs/toc.json`、`inputs/toc.md`：切章和目录持久化。
4. `profile/project_profile.json|md`：依据真实投标内容生成项目概况。
5. `outline/generated_outline.json|md`：依据项目概况、投标目录和模板树生成四模块目录规划。
6. `mapping/{node_id}.json`：每个模板小章节生成前先匹配真实来源章节。
7. `chapters/{node_id}.md`：把映射到的原输入章节全文加入提示词后，逐小章节生成严格 Markdown。
8. `runs/{run_id}/validation.json`：记录校验、来源映射和任务状态。
9. `artifacts/final.md`：所有章节通过后合并的完整施组 Markdown。

## Run API

```powershell
$env:PYTHONPATH="src"
python -m coalplan.main
```

API 文档默认在 `http://127.0.0.1:8010/docs`。

更完整的接口与工作台使用说明见：

- `docs/stable-convergence-v0.1.md` - stable v0.1 demo entry and guardrail checklist.
- `docs/api-workbench.md`
- `docs/v0.1-runbook.md`
- `docs/run-with-deepseek.md`

## Run Web

```powershell
cd src/coalplan/web
npm install
npm run dev
```

前端默认在 `http://127.0.0.1:5174`。

## Demo API Flow

- `GET /templates`：模板陈列列表。
- `GET /templates/{template_id}`：查看模板目录树与四模块。
- `POST /projects`：按所选模板创建项目。
- `POST /projects/{project_id}/template`：生成前切换项目模板。
- `POST /projects/{project_id}/bid-markdown`：上传投标 Markdown，并自动规范化、切章、生成来源目录。
- `POST /projects/{project_id}/directory`：生成项目概况、模板化目录规划和待生成小章节任务。
- `GET /projects/{project_id}/directory`：查看来源目录、模板目录、生成目录规划和章节任务。
- `GET /projects/{project_id}/source-toc`：查看原输入文档切章目录。
- `GET /projects/{project_id}/sections/{section_id}`：查看原输入文档某个切分章节全文。
- `GET /projects/{project_id}/chapters`：查看待生成/已生成章节任务。
- `POST /projects/{project_id}/chapters/{node_id}/generate`：逐章生成，并先执行来源映射。
- `GET /projects/{project_id}/chapters/{node_id}`：查看单章生成结果与映射来源。
- `POST /projects/{project_id}/generate`：全量逐章生成。
- `POST /projects/{project_id}/merge`：合并已通过章节。
- `GET /projects/{project_id}/artifacts/final.md`：查看最终 Markdown。

## DeepSeek V4

不要把真实 key 写入仓库文件。使用本机环境变量：

```powershell
$env:COALPLAN_LLM_PROVIDER="deepseek"
$env:COALPLAN_DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:COALPLAN_DEEPSEEK_API_KEY="replace-me"
$env:COALPLAN_DEEPSEEK_MODEL="deepseek-v4-pro"
$env:COALPLAN_LLM_TRACE_DIR=".coalplan-real-run-deepseek\llm-traces"
```

`deepseek-v4-pro` 适合具体章节正文生成；需要更快或更省成本时可改为 `deepseek-v4-flash`。

## MiniMax

```powershell
$env:COALPLAN_LLM_PROVIDER="minimax"
$env:COALPLAN_MINIMAX_BASE_URL="https://api.minimaxi.com/v1"
$env:COALPLAN_MINIMAX_API_KEY="replace-me"
$env:COALPLAN_MINIMAX_MODEL="MiniMax-M2.7"
```

也可以继续用本地演示模型：

```powershell
$env:COALPLAN_LLM_PROVIDER="source_driven"
```

## Real Bid Demo

```powershell
$env:PYTHONPATH="src"
python -m coalplan.interfaces.cli.generate_from_markdown `
  data\real_inputs\ningxia_coal_fire_bid.normalized.md `
  --project-name "宁夏煤火北一火区真实投标演示" `
  --output-dir .coalplan-real-run-pipeline `
  --llm-provider source_driven
```

使用 DeepSeek V4：

```powershell
$env:PYTHONPATH="src"
$env:COALPLAN_DEEPSEEK_API_KEY="replace-me"
$env:COALPLAN_LLM_TRACE_DIR=".coalplan-real-run-deepseek\llm-traces"
python -m coalplan.interfaces.cli.generate_from_markdown `
  data\real_inputs\ningxia_coal_fire_bid.normalized.md `
  --project-name "宁夏煤火北一火区 DeepSeek 演示" `
  --output-dir .coalplan-real-run-deepseek `
  --llm-provider deepseek
```

## Convert DOCX To Markdown

```powershell
$env:PYTHONPATH="src"
python tools\docx_to_markdown.py `
  "D:\Task\方案大模型资料\方案大模型资料\1.宁夏煤火\投标文件-商务-技术-报价清单\技术\宁夏贺兰山汝箕沟太西煤火区安全与生态治理项目一期工程北一火区治理施工项目技术文件（2025.6.16）终版.docx" `
  data\real_inputs\ningxia_coal_fire_bid.raw.md

python -m coalplan.interfaces.cli.normalize_markdown `
  data\real_inputs\ningxia_coal_fire_bid.raw.md `
  data\real_inputs\ningxia_coal_fire_bid.normalized.md
```

## Tests

```powershell
$env:PYTHONPATH="src"
python -m compileall -q src
python -m unittest discover -s tests

cd src/coalplan/web
npm run build
```
