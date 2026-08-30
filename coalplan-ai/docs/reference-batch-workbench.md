# 水电施组大批次原子整理工作台

本工作台用于在不调用外部 LLM API 的情况下，准备和接收当前模型完成的水电施组原子审查结果。

## 1. 准备任务包

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m coalplan.interfaces.cli.reference_batch prepare `
  --source-root 'D:\Task_md\安能-数据-markdown' `
  --catalog '.coalplan-data\reference-library\catalog\reference_corpus_catalog.json' `
  --output-dir '.coalplan-data\reference-library\large-batch' `
  --batch-size 3
```

任务包中的 `batch_*.json` 包含源文档身份、标题路径、行号和原文 block。当前模型按每批任务包生成同名决定文件，放入单独的 `decisions` 目录。

决定文件格式为：

```json
{
  "documents": [
    {
      "document_id": "refdoc_xxx",
      "atoms": [
        {
          "block_ids": ["refblock_xxx"],
          "reference_value": "high",
          "value_reason": "包含完整工序和验收闭环",
          "reuse_scope": ["水电隧洞钻爆开挖"],
          "migration_warning": ["项目参数不得直接迁移"],
          "process": "钻爆开挖",
          "content_functions": ["工艺流程", "质量检查"],
          "fact_variables": []
        }
      ]
    }
  ]
}
```

模型不得返回改写后的正文。导入器会按照 `block_ids` 从任务包回拼原文；正文不一致、引用不存在 block、内容过短或价值不是 `high` 的记录都会被淘汰。

## 2. 导入审查结果

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m coalplan.interfaces.cli.reference_batch ingest `
  --task-dir '.coalplan-data\reference-library\large-batch\<run_id>\tasks' `
  --decision-dir '.coalplan-data\reference-library\large-batch\<run_id>\decisions' `
  --output-dir '.coalplan-data\reference-library\large-batch\<run_id>\library'
```

如需让管理台立即显示批量整理结果，在上述命令后增加 `--sync-database`。该选项会将文档、章节范围和已发布原子幂等同步到应用使用的 SQLite；批次 JSONL 仍是审计产物，重复执行不会新增重复记录。

产物包括：

- `reference_atom_library.jsonl`：仅含高参考价值、可追溯原子。
- `rejected_atoms.jsonl`：低价值、重复或格式不合格记录及原因。
- `document_processing.csv`：文档完成和待续跑状态。
- `dedup_groups.json`：模型语义去重组。
- `summary.json`、`summary.md`：处理量和工艺覆盖汇总。

源目录保持只读。缺少决定文件的批次会出现在 `missing_batches` 中，可补齐决定文件后重复执行导入，不影响其他批次。
