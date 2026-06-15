# Phase 1 Requirement Traceability

本文件用于把第一阶段目标拆成可检查项，避免后续开发偏离“火区治理投标 Markdown 到施组 Markdown”的核心闭环。

| 目标要求 | 当前实现 | 验证证据 |
| --- | --- | --- |
| 以火区治理投标文档为输入 | `POST /projects/{id}/bid-markdown` 接收 Markdown；`ingest_bid_markdown.py` 写入原文和规范化文件 | `tests/integration/test_coal_fire_pipeline_fake_llm.py` |
| 处理一份 Markdown 输入规范 | `docs/markdown_input_spec.md` 定义标题、切章和推荐内容规范 | 文档审阅；`tests/unit/test_markdown_canonicalizer.py` |
| 将投标 Markdown 裁剪成章节 | `MarkdownDocumentParser` 组合 `MarkdownCanonicalizer` 与 `MarkdownSectionSplitter` | `tests/unit/test_section_splitter.py` |
| 按火区治理模板目录树生成 | `MarkdownTemplateLoader` 读取 `assets/templates/coal_fire_template.md` | `tests/unit/test_template_loader.py` |
| 分小章节单次生成 Markdown | `GenerationPipeline.generate_all` 遍历 `ChapterTask`；`generate_chapter.py` 每节写入 `chapters/{node_id}.md` | `tests/integration/test_coal_fire_pipeline_fake_llm.py` |
| 自动从投标文档获取对应信息 | `KeywordSourceRetriever` 依据模板节点和来源规则召回 `SourceMatch`；API 返回 `source_matches`；前端展示来源片段 | `tests/unit/test_source_retriever.py`；接口复核 |
| 严格控制 LLM 输出格式 | `MarkdownContractValidator` 要求固定标题和模块，拒绝 JSON、缺来源、缺人工占位、疑似编造参数 | `tests/unit/test_output_contract.py` |
| 生成失败时避免流程错误 | 生成前必须存在投标章节；校验失败先修复，仍失败则 task failed；合并前检查所有 task passed | `test_generation_requires_bid_markdown_sections`；`merge_chapters.py` |
| 全部小章节完成后合并 | `merge_template_tree_markdowns` 按模板树顺序输出父级标题和小节正文 | `test_end_to_end_generation_and_merge` |
| 简要前端展示 | `web/src/App.tsx` 三栏展示项目输入、模板树、来源片段、单章结果、日志和合并结果 | `npm run build` |
| 模块化 Python 大型工程结构 | `domain/application/ports/infrastructure/interfaces` 分层；FastAPI 与 LLM/存储/检索解耦 | `docs/phase1_architecture.md` |
| 后续模板复用、低耦合 | 模板加载、检索、LLM、存储均通过 ports 注入；火区模板只是 `template_id=coal_fire` 的资产 | `GenerationPipeline.__init__`；`ports/*.py` |

## 第一阶段未纳入范围

以下能力属于完整需求规格说明书的后续阶段，本阶段只预留结构，不作为完成标准：

- PDF/Word/CAD/OCR 输入解析。
- Word/PDF 企业模板套版导出。
- 图纸生成或图纸一致性审查。
- 施工方案智能审查。
- 知识库管理后台、规范失效管理和反馈闭环。
- 用户权限、数据隔离、审计日志、存储加密。
- 异步队列、站内消息、版本对比和局部流式修改。

## 当前风险

- 目前默认 `KeywordSourceRetriever` 是可解释的首期检索器，不是最终语义检索。后续需要接入向量检索、rerank 或 LLM source-mapping agent。
- 默认 `FakeLLMClient` 用于流程验证；真实模型接入需用私有化 OpenAI-compatible 服务，并扩展提示词回归测试。
- 当前前端是演示工作台，不是最终对话式产品界面。
