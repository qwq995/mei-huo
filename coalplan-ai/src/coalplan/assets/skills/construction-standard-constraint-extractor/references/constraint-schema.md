# 约束原子契约

每条约束包含：

- `block_id`、`clause_no`、`source_text`：原文定位。
- `normalized_requirement`：面向审查的简明要求。
- `constraint_type`：`禁止性要求`、`强制性要求`、`数值阈值`、`允许偏差`、`工序闭环`、`资质审批`、`验收记录`、`适用条件`、`一般技术要求`。
- `review_method`：`semantic_review`、`numeric_compare`、`presence_check`、`evidence_check`、`applicability_check`。
- `severity`：`blocking`、`warning`、`advisory`。
- `disciplines`、`project_types`、`chapter_scopes`、`keywords`：双层匹配标签。
- `applicability`、`exceptions`、`evidence_required`：适用与证据边界。
- `ai_fixable`、`repair_instruction`：修复能力和操作说明。
- `confidence`、`status`：置信度与 `published|ai_candidate` 状态。

审查发现项必须附带 `standard_code`、`standard_name`、`clause_no`、`constraint_text`、章节版本、违规说明、正文证据、是否可由 AI 解决以及建议动作。
