# 优秀施组原子要素库实现说明

## 1. 目标与事实边界

章节生成使用三类相互隔离的信息：

1. 当前项目投标文档和用户补充是工程量、参数、位置、工期、设备及规范版本等项目事实的唯一来源。
2. 已发布的异项目参考原子只提供工艺步骤、控制维度、检查验收闭环和专业表达。
3. 写作模式库只提供章节组织规则和提示词，不提供项目事实。

参考文档使用独立的 `reference_documents`、`reference_chapters`、`reference_atoms` 和
`chapter_atom_usages` 表，不写入项目 `source_documents/source_sections`。

## 2. 本地语料分类

只读扫描命令：

```powershell
$env:PYTHONPATH='src'
python -X utf8 -m coalplan.interfaces.cli.catalog_reference_corpus `
  --source-root 'D:\Task_md\安能-数据-markdown' `
  --output-dir '.coalplan-data\reference-library\catalog'
```

当前扫描结果：

- Markdown 文件 1823 份，唯一内容 1787 份。
- 完全重复副本 36 份。
- 经文件身份、路径、内容结构和质量门禁筛选后，原子候选文档 418 份。
- 招标、投标、合同、工程量清单、初设和图纸资料保留为项目证据类，不进入参考原子候选池。

输出包括 JSON、UTF-8 BOM CSV 和 Markdown 汇总。源目录全程只读，不移动、不重命名、不覆盖原文件。

## 3. AI 自动切分与标注

`reference_atomization.py` 先按标题、段落、连续列表和表格边界生成带行号的预切块。对于转换后全部使用
`##` 的 Markdown，会优先根据 `3.4.5.2` 等数字编号推断层级。

模型不直接返回改写后的原子正文，而是返回：

- 应合并的 `block_id`；
- 工程对象、专业、分部分项、工艺、工序阶段和章节类型；
- 内容功能、适用条件和禁止套用场景；
- 项目名称、地名、工程量、设备数量、施工参数及规范版本等事实变量；
- 完整性质量分和标注置信度。

系统根据模型选择的 `block_id` 从原 Markdown 拼回正文。相同来源块集合只产生一个稳定 `atom_id`，
避免模型用不同标签重复输出同一正文造成主键冲突。

默认状态为 `ai_candidate`。正式检索只读取 `published` 原子；`publish_for_validation` 仅用于少量验证，
且要求置信度不低于 0.75、质量分不低于 0.65。

## 4. AI 自动匹配

匹配分为两级：

1. 本地预筛按项目类型、章节标题、上下级标题、投标证据摘要、写作主题和原子标签计算可解释分数，最多保留
   24 条候选。
2. 结构化模型依据工程对象、工艺、适用条件和内容互补性重排，默认选择 3 至 6 条。

以下内容在预筛阶段直接排除：

- 与当前项目同名的参考项目；
- 未发布、已退回或已拒绝的原子；
- 用户明确排除的项目；
- 工程对象或适用条件明显冲突的候选。

章节版本的生成元数据保存 `atom_id`、检索分数、匹配理由、允许借鉴内容、来源项目和标题路径。
`chapter_atom_usages` 另存每次实际选择记录。

## 5. 提示词隔离与泄漏审计

章节提示词新增独立的“优秀施组参考原子（异项目、非事实来源）”区域。每条原子明确列出事实变量和
“不得直接迁移”标识。生成规则要求当前项目证据冲突时以投标证据为准，无证据时使用人工补充占位。

生成后执行反向泄漏审计：

1. 提取参考原子中的显式事实变量、带单位参数和规范编号。
2. 检查生成正文是否使用这些值。
3. 检查相同值是否存在于当前项目证据、用户补充或质量反馈确认事实中。
4. 对仅来自异项目原子的值执行一次受控修复，再次审计。
5. 二次审计仍有问题时，章节状态改为 `needs_repair`，不得按通过版本合并。

## 6. API 与 CLI

Swagger 中提供：

- `GET /reference-library/documents`
- `GET /reference-library/atoms`
- `POST /reference-library/import-ai`
- `PATCH /reference-library/atoms/{atom_id}/status`
- `POST /reference-library/retrieve`
- `GET /reference-library/usage/{project_id}`

CLI 示例：

```powershell
python -X utf8 -m coalplan.interfaces.cli.reference_atoms import 'D:\sample.md' `
  --project-name '扎拉' --project-type '水电/导流隧洞/边坡' `
  --focus '洞身开挖' --publish-for-validation

python -X utf8 -m coalplan.interfaces.cli.reference_atoms retrieve `
  --project-name '拉哇' --project-type '水电/泄洪洞' `
  --chapter-title '泄洪洞洞身开挖与支护' --topic '钻爆开挖'
```

## 7. 真实跨项目验证

验证目标为拉哇泄洪系统投标文档的“泄洪洞洞身开挖与支护”章节。当前项目事实只取投标文件
`3.4.4/3.4.5` 相关章节；原子来自扎拉导流洞和靖宇交通洞，强制排除拉哇自身参考施组。

使用 `deepseek-v4-flash` 完成两次切分标注、一次 AI 重排、基线/增强生成和一次泄漏修复：

| 指标 | 基线 | 原子增强 |
| --- | ---: | ---: |
| 工序词覆盖率 | 0.615 | 0.923 |
| 控制闭环词覆盖率 | 0.500 | 0.800 |
| 最终参考事实泄漏 | - | 0 |

初始增强稿曾迁移异项目爆破半孔率等 7 项参数。自动修复删除或定性化这些参数，二次审计为 0。
这说明仅靠提示词不足以保证事实边界，生成后的程序化门禁是必要环节。

复现命令：

```powershell
python -X utf8 -m coalplan.interfaces.cli.validate_reference_atoms_lawa
```

结果位于 `.coalplan-data/reference-library/validation/lawa_cross_project/`，包括 `baseline.md`、
`enhanced_raw.md`、`enhanced.md`、召回原子、指标报告及六次模型调用 trace。

## 8. 已先行处理的问题

- 转换后 Markdown 标题层级失真：使用数字编号辅助恢复层级。
- 审批封面、专家意见和目录混入正文：AI 提示明确排除，分类层另设质量反馈用途。
- 正文中出现“施工组织设计”导致招标合同误分类：文件名和目录身份优先于正文弱特征。
- 同一原文块被模型重复打标签：按来源块集合生成稳定 ID，并在仓储写入前再次去重。
- 模型忽略“不得迁移参数”约束：增加生成后泄漏审计、受控修复和二次门禁。
- 同项目参考造成答案泄漏：检索预筛强制排除当前项目和指定项目。

## 9. 当前限制

- 全量 418 份候选尚未批量调用模型，仅对两个真实异项目来源做了小规模验证。
- 首版采用本地关键词/标签预筛加 AI 重排，尚未引入本地向量模型；这样可避免模型下载和部署依赖先阻断主流程。
- 自动高置信发布只用于验证。生产数据仍应经过人工审核后发布。
- 当前泄漏审计聚焦显式变量、带单位数值和规范编号，后续需要扩展项目专有地名、设备型号及同义格式归一化。
