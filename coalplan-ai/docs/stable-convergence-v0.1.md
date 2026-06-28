# CoalPlan AI v0.1 收束版说明

本文只记录当前可稳定演示的闭环，不再扩展新能力。

## 当前可用边界

- 输入 Markdown 投标文件后，可以持久化 source toc、sections、project profile。
- 模板会复制为项目自己的可编辑目录树。
- 目录 proposal 是硬门禁：存在 pending outline proposal 时，系统必须先等待用户 apply，不能继续生成正文。
- 用户确认目录后，系统进入 source mapping / generation 阶段。
- 章节生成前会先做来源映射和证据抽取。
- 生成结果会保存 chapter version、content tree、evidence audit、generation metadata。
- readiness 能判断下一步是生成、拆小节、修订、人工补充、版本确认或合并。
- readiness batch 只执行 auto action，不会自动应用需要用户确认的 proposal。
- 分支生成失败不会中断整个流程，会返回 child 失败项、失败原因、next_action 和 revision endpoint。
- 证据遗漏类失败会进入定向修订，而不是盲目重试。

## 必须遵守的门禁

1. 有 pending outline proposal 时，当前窗口必须是 `waiting_for_user`。
2. 只有 apply proposal 后，才能进入 `auto_runnable`。
3. 没有来源映射的事实性章节不能正常生成事实正文。
4. 大型工艺章节优先拆成小节，再逐小节映射和生成。
5. `omitted_required_source_facts`、`omitted_feedback_required_facts`、`manual_item_has_source_support` 必须进入下一轮 revision context。
6. 最终合并只读取用户选中的 chapter version。

## 推荐演示路径

1. 创建项目并选择模板。
2. 上传标准 Markdown 投标文件。
3. 生成目录。
4. 如果 current window 出现 `apply_pending_outline_proposal`，先应用 proposal。
5. 查看 source toc、project profile、outline nodes。
6. 估算或手动填写目标字数。
7. 对代表章节添加人工补充或附件说明。
8. 用 readiness 面板执行小批自动生成，建议 limit 为 2 到 3。
9. 查看 batch execution report。
10. 对失败 child 查看 `next_action` 和 `endpoint`。
11. 对 `needs_revision` 的章节执行 revision-action。
12. 查看 version、content tree、evidence audit、generation metadata。
13. 选择版本后再 merge。

## project3 当前验证结论

在 project3 副本中验证通过：

- pending outline proposal 可阻塞生成。
- apply proposal 后 current window 可解锁。
- readiness batch 可执行小批生成。
- child branch 可部分成功。
- child branch 失败时不会再出现代码异常。
- 失败项会返回：
  - `node_id`
  - `error`
  - `next_action: regenerate`
  - `endpoint: /projects/{project_id}/chapters/{node_id}/revision-action`

典型失败原因已收束为质量门禁：

- `omitted_required_source_facts`
- `omitted_feedback_required_facts`
- `manual_item_has_source_support`

这些原因会被带入下一轮 revision context。

## 验证命令

后端关键验证：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai
$env:PYTHONPATH="src"
python -X utf8 -m unittest tests.unit.test_revision_decision tests.unit.test_generation_readiness_batch_execution tests.integration.test_generation_control_api
```

前端构建：

```powershell
cd C:\Users\Lenovo\Documents\煤火\coalplan-ai\src\coalplan\web
npm run build
```

最近一次验证结果：

- 后端测试通过。
- 前端 build 通过。

## 现在不继续扩展的内容

- 不做全量 project4 验证。
- 不做图纸、多模态、云端回写。
- 不新增复杂自动学习策略。
- 不追求一次生成达到人工施组终稿。
- 不绕过用户确认去自动应用目录 proposal。

## 下一步只建议做一件事

用 project3 正本或副本选择 2 到 3 个代表章节，执行：

```text
apply proposal -> readiness batch -> revision-action -> inspect evidence audit -> select version
```

如果这条链路稳定，再整理演示数据包；否则只修这条链路暴露出的 bug。
