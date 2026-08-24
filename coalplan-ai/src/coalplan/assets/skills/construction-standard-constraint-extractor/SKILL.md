---
name: construction-standard-constraint-extractor
description: Extract traceable compliance constraints from one Chinese engineering-standard Markdown document. Use when importing, classifying, atomizing, reviewing, or matching 水利水电/施工/安全/质量验收 standards for final construction-plan compliance review.
---

# 规范约束拆分

把每份规范作为独立、可启停、可追溯的管理单元。将规范原文拆成可匹配的约束原子，但只在成稿审查阶段使用约束，不参与目录生成、章节写作或事实补充。

## 工作流

1. 将多份文档按不超过 10 份一批交给 AI，从文件名、首页和总则统一识别专业、项目类型及规范类别；不要用固定专业词表分类。标准编号和名称只做格式解析。
2. 按 Markdown 标题、条款编号、连续列表和完整表格建立原文块；不要拆散同一条款的条件、主句和例外。
3. 从原文块提取单一可判断要求。跳过前言、目录、术语定义、引用文件列表和纯解释性文字。
4. 保存条款编号、标题路径、原文行号和逐字原文。标准化要求只能概括审查目标，不能替代原文。
5. 标注约束类型、审查方式、适用条件、章节主题、专业关键词、严重程度和证据要求。
6. 仅在置信度不低于 0.72 且原文明确时自动发布；其余进入候选状态供快速抽查。
7. 先由 AI 分批匹配规范文档，再由 AI 在已选规范内分批匹配具体约束；不要使用关键词计数决定相关性，仅将少量高相关约束送入成稿审查。
8. 审查只报告明确违反或明确缺失必要措施的条款。无法判断时标记“需人工确认”，不要推定违规。

## 修复边界

- 仅当删除冲突措辞、补全已有依据支持的步骤或完善控制措施即可合规时，标记 `ai_fixable=true`。
- 涉及资质、审批、检测报告、现场实测、设计参数、工程量、设备能力或项目事实缺失时，必须标记 `ai_fixable=false`。
- AI 修复必须创建新章节版本，保留旧版本，并要求重新审查。
- 不得用规范原子为当前项目虚构事实、参数或已完成的审批结论。

## 输出要求

读取 [constraint-schema.md](references/constraint-schema.md) 并遵守字段枚举。原子 `source_text` 必须能够在对应原文块中逐字定位；无法定位的候选必须丢弃。
