# 参考语料与原子库交付包

## 代码与数据边界

GitHub 仓库只保存原子化、审核、检索、向量索引和章节接入代码，以及受控标签和 JSON Schema。下列数据不进入 Git：

- 真实施组、投标文档和专项计划。
- 物化后的原子语料、处理检查点和模型调用轨迹。
- SQLite 用户项目数据库和 Qdrant 本地索引。
- `.env`、API Key、日志和前端构建产物。

可交付数据由 `scripts/reference_library/build_delivery_package.py` 生成独立 ZIP。

## 仓库结构

```text
config/reference_library/
  reference_atom_taxonomy.v2.json
  reference_atom_query_v2.output.schema.json
  reference_atomization_v2.output.schema.json
  reference_section_routing_v2.output.schema.json

scripts/reference_library/
  build_delivery_package.py
  recommend_reference_v2_validation_atoms.py
  validate_reference_v2_chapter_generation.py
  validate_reference_v2_retrieval.py

docs/reference-library/
  v2.md
  delivery-package.md
```

## 构建命令

```powershell
$env:PYTHONPATH="src"
python scripts/reference_library/build_delivery_package.py `
  --cleaned-root "D:\Task_md\安能-数据-markdown\方案大模型资料\方案大模型资料_清洗归类_最终_20260908" `
  --corpus-root ".coalplan-data\reference-library\v2-corpus" `
  --vector-root ".coalplan-data\reference-vectors" `
  --database ".coalplan-data\coalplan.db" `
  --taxonomy "config\reference_library\reference_atom_taxonomy.v2.json" `
  --schemas "config\reference_library" `
  --architecture-doc "docs\reference-library\v2.md" `
  --output "D:\Task_md\安能-数据-markdown\方案大模型资料\施工方案语料与原子库_20260909.zip"
```

## 交付包结构

```text
01_清洗文档/
  施组文档/
  投标文档/
  专项计划/
  清洗过程与清单/
02_原子库/
  library_export/
  processing_assets/
03_向量索引/
  reference-vectors/
04_配置与说明/
05_清单校验/
  manifest.json
README.md
```

`library_export` 只导出参考文档、来源章节和 V2 原子，不包含用户项目、章节正文、项目记忆或原子使用记录。

## 校验

ZIP 内的 `manifest.json` 记录每个文件的相对路径、字节数和 SHA-256。解压后可通过该清单检查文件是否完整。
