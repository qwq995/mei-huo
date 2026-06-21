import { useEffect, useMemo, useState } from "react";
import {
  addSupplement,
  applyChapterProposal,
  applyOutlineProposal,
  createManualVersion,
  createOutlineNode,
  createProject,
  deleteOutlineNode,
  estimateOutlineWordCounts,
  generateChapter,
  generateDirectory,
  generateProject,
  getDirectory,
  getFinalMarkdown,
  getTemplateTree,
  getWorkspace,
  listOutlineNodes,
  listProjects,
  listTemplates,
  mergeProject,
  proposeChapterEdit,
  proposeOutlineAIPlan,
  proposeOutlineChange,
  selectVersion,
  updateOutlineNode,
  updateVersionContentNode,
  uploadAttachment,
  uploadBidMarkdown,
  API_BASE,
  type AIProposal,
  type ChapterSupplement,
  type ChapterVersion,
  type ChapterWorkspace,
  type DirectoryResponse,
  type GeneratedContentNode,
  type OutlineNode,
  type ProjectResponse,
  type SourceTocItem,
  type TemplateNode,
  type TemplateSummary
} from "./api";

const defaultMarkdown = "# 章节标题\n\n## 主要来源摘要\n\n## 生成正文\n\n## 人工补充需补充\n";

type Notice = { kind: "ok" | "warn"; text: string };

export default function App() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [templateId, setTemplateId] = useState("coal_fire");
  const [templateTree, setTemplateTree] = useState<TemplateNode[]>([]);
  const [projectName, setProjectName] = useState("施工组织设计生成演示");
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [directory, setDirectory] = useState<DirectoryResponse | null>(null);
  const [outlineNodes, setOutlineNodes] = useState<OutlineNode[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<ChapterWorkspace | null>(null);
  const [editorMarkdown, setEditorMarkdown] = useState(defaultMarkdown);
  const [supplement, setSupplement] = useState({ kind: "text", title: "", content: "", must_include: true });
  const [attachmentDescription, setAttachmentDescription] = useState("");
  const [newNodeTitle, setNewNodeTitle] = useState("");
  const [outlineSuggestion, setOutlineSuggestion] = useState("");
  const [referenceMarkdown, setReferenceMarkdown] = useState("");
  const [outlineAIProposal, setOutlineAIProposal] = useState<AIProposal | null>(null);
  const [chapterSuggestion, setChapterSuggestion] = useState("");
  const [selectedContentNodeId, setSelectedContentNodeId] = useState<string | null>(null);
  const [finalMarkdown, setFinalMarkdown] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>({ kind: "ok", text: `后端地址：${API_BASE}` });

  useEffect(() => {
    void Promise.all([listTemplates(), listProjects()])
      .then(([templateItems, projectItems]) => {
        setTemplates(templateItems);
        setProjects(projectItems);
        if (templateItems[0]) setTemplateId(templateItems[0].template_id);
      })
      .catch(showError);
  }, []);

  useEffect(() => {
    if (!templateId) return;
    void getTemplateTree(templateId).then(setTemplateTree).catch(showError);
  }, [templateId]);

  useEffect(() => {
    if (!project?.id || !selectedNodeId) {
      setWorkspace(null);
      setSelectedContentNodeId(null);
      return;
    }
    void refreshWorkspace(project.id, selectedNodeId).catch(showError);
  }, [project?.id, selectedNodeId]);

  const selectedNode = useMemo(
    () => outlineNodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [outlineNodes, selectedNodeId]
  );
  const sourceItems = directory?.source_toc?.items ?? [];
  const selectedVersion = workspace?.versions.find((version) => version.id === workspace.selected_version_id) ?? null;
  const contentNodes = useMemo(() => flattenContentNodes(selectedVersion?.content_tree?.nodes ?? []), [selectedVersion]);
  const selectedContentNode = contentNodes.find((node) => node.id === selectedContentNodeId) ?? null;
  const wordStats = useMemo(() => {
    const withTarget = outlineNodes.filter((node) => Number(node.target_word_count ?? 0) > 0);
    const total = withTarget.reduce((sum, node) => sum + Number(node.target_word_count ?? 0), 0);
    return { withTarget: withTarget.length, total };
  }, [outlineNodes]);
  const workflowSteps = useMemo(
    () => [
      { label: "创建项目", done: Boolean(project) },
      { label: "上传投标", done: Boolean(project?.section_count) },
      { label: "生成目录", done: outlineNodes.length > 0 },
      { label: "字数目标", done: wordStats.withTarget > 0 },
      { label: "章节生成", done: Boolean(selectedVersion) },
      { label: "合并预览", done: Boolean(finalMarkdown) }
    ],
    [project, outlineNodes.length, wordStats.withTarget, selectedVersion, finalMarkdown]
  );

  function showError(error: unknown) {
    setNotice({ kind: "warn", text: error instanceof Error ? error.message : String(error) });
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function refreshProjects(selectId?: string) {
    const items = await listProjects();
    setProjects(items);
    if (selectId) setProject(items.find((item) => item.id === selectId) ?? null);
  }

  async function refreshDirectory(projectId = project?.id) {
    if (!projectId) return;
    const data = await getDirectory(projectId);
    setDirectory(data);
    setProject(data.project);
    const nodes = await listOutlineNodes(projectId);
    setOutlineNodes(nodes);
    if (!selectedNodeId && nodes[0]) setSelectedNodeId(nodes[0].node_id);
  }

  async function refreshWorkspace(projectId = project?.id, nodeId = selectedNodeId) {
    if (!projectId || !nodeId) return;
    const data = await getWorkspace(projectId, nodeId);
    setWorkspace(data);
    const selected = data.versions.find((version) => version.id === data.selected_version_id) ?? data.versions[0];
    setEditorMarkdown(selected?.markdown ?? `# ${data.outline_node.title}\n\n## 主要来源摘要\n\n## 生成正文\n\n## 人工补充需补充\n`);
    setSelectedContentNodeId(null);
  }

  function openProject(item: ProjectResponse) {
    setProject(item);
    setTemplateId(item.template_id);
    setSelectedNodeId(null);
    setWorkspace(null);
    setFinalMarkdown("");
    setOutlineAIProposal(null);
    setSelectedContentNodeId(null);
    void refreshDirectory(item.id).catch(showError);
  }

  async function handleCreateProject() {
    await run(async () => {
      const created = await createProject(projectName.trim() || "施工组织设计项目", templateId);
      setProject(created);
      setDirectory(null);
      setOutlineNodes([]);
      setSelectedNodeId(null);
      setWorkspace(null);
      setFinalMarkdown("");
      setOutlineAIProposal(null);
      await refreshProjects(created.id);
      setNotice({ kind: "ok", text: `已创建项目：${created.name}` });
    });
  }

  async function handleUpload(file?: File | null) {
    if (!project || !file) return;
    await run(async () => {
      const content = await file.text();
      const updated = await uploadBidMarkdown(project.id, file.name, content);
      setProject(updated);
      setDirectory(null);
      setOutlineNodes([]);
      setWorkspace(null);
      setFinalMarkdown("");
      setOutlineAIProposal(null);
      await refreshProjects(updated.id);
      setNotice({ kind: "ok", text: `已上传并切分：${updated.section_count} 个来源章节` });
    });
  }

  async function handleGenerateDirectory() {
    if (!project) return;
    await run(async () => {
      const data = await generateDirectory(project.id);
      setDirectory(data);
      setProject(data.project);
      const nodes = await listOutlineNodes(project.id);
      setOutlineNodes(nodes);
      setSelectedNodeId(nodes[0]?.node_id ?? null);
      setNotice({
        kind: data.warnings.length ? "warn" : "ok",
        text: data.warnings[0] ?? `基础目录已生成：${nodes.length} 个可编辑节点`
      });
    });
  }

  async function handleReferenceFile(file?: File | null) {
    if (!file) return;
    setReferenceMarkdown(await file.text());
    setNotice({ kind: "ok", text: `已载入参考施组：${file.name}` });
  }

  async function handleEstimateWordCounts() {
    if (!project) return;
    await run(async () => {
      const result = await estimateOutlineWordCounts(project.id, referenceMarkdown);
      setOutlineNodes(result.nodes);
      if (selectedNodeId) await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: `已为 ${result.estimates.length} 个目录节点估算目标字数` });
    });
  }

  async function handleAIPlanOutline() {
    if (!project) return;
    await run(async () => {
      const proposal = await proposeOutlineAIPlan(project.id, outlineSuggestion.trim() || "请基于项目概况、投标目录和模板四模块优化项目目录。");
      setOutlineAIProposal(proposal);
      setOutlineSuggestion("");
      setNotice({ kind: "ok", text: `AI 目录优化建议已生成：${proposal.id}，确认后才会应用` });
    });
  }

  async function handleOutlineProposal() {
    if (!project || !outlineSuggestion.trim()) return;
    await run(async () => {
      const proposal = await proposeOutlineChange(project.id, outlineSuggestion.trim());
      setOutlineAIProposal(proposal);
      setOutlineSuggestion("");
      setNotice({ kind: "ok", text: `已生成目录修改预览：${proposal.id}` });
    });
  }

  async function handleUpdateNode() {
    if (!project || !selectedNode) return;
    await run(async () => {
      await updateOutlineNode(project.id, selectedNode.node_id, selectedNode);
      await refreshDirectory(project.id);
      await refreshWorkspace(project.id, selectedNode.node_id);
      setNotice({ kind: "ok", text: `已保存目录节点：${selectedNode.title}` });
    });
  }

  async function handleCreateNode(parentId?: string | null) {
    if (!project || !newNodeTitle.trim()) return;
    await run(async () => {
      const parent = parentId ? outlineNodes.find((node) => node.node_id === parentId) : null;
      const created = await createOutlineNode(project.id, {
        parent_id: parentId ?? null,
        title: newNodeTitle.trim(),
        level: parent ? parent.level + 1 : 1,
        source_rules: [],
        auto_fill: [],
        manual_fill: ["【需人工补充：本章节必要资料。】"],
        special_notes: [],
        target_word_count: 800
      });
      setNewNodeTitle("");
      await refreshDirectory(project.id);
      setSelectedNodeId(created.node_id);
      setNotice({ kind: "ok", text: `已新增目录节点：${created.title}` });
    });
  }

  async function handleDeleteNode() {
    if (!project || !selectedNode) return;
    await run(async () => {
      await deleteOutlineNode(project.id, selectedNode.node_id);
      setSelectedNodeId(null);
      setWorkspace(null);
      await refreshDirectory(project.id);
      setNotice({ kind: "ok", text: "目录节点已删除" });
    });
  }

  async function handleAddSupplement() {
    if (!project || !selectedNodeId || !supplement.title.trim() || !supplement.content.trim()) return;
    await run(async () => {
      await addSupplement(project.id, selectedNodeId, supplement);
      setSupplement({ kind: "text", title: "", content: "", must_include: true });
      await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: "补充材料已保存，刷新页面后仍会保留" });
    });
  }

  async function handleAttachment(file?: File | null) {
    if (!project || !selectedNodeId || !file) return;
    await run(async () => {
      await uploadAttachment(project.id, selectedNodeId, file, attachmentDescription);
      setAttachmentDescription("");
      await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: "附件已保存为本地 artifact，并进入章节工作区" });
    });
  }

  async function handleGenerateChapter() {
    if (!project || !selectedNodeId) return;
    await run(async () => {
      const response = await generateChapter(project.id, selectedNodeId);
      setEditorMarkdown(response.version?.markdown ?? response.markdown);
      await refreshDirectory(project.id);
      await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: `已生成新版本：${response.title}` });
    });
  }

  async function handleSaveManualVersion() {
    if (!project || !selectedNodeId) return;
    await run(async () => {
      await createManualVersion(project.id, selectedNodeId, selectedNode?.title ?? "手动版本", editorMarkdown, true);
      await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: "手动编辑已保存为新版本" });
    });
  }

  async function handleSaveContentNode() {
    if (!project || !selectedNodeId || !selectedVersion || !selectedContentNodeId) return;
    await run(async () => {
      const newVersion = await updateVersionContentNode(project.id, selectedNodeId, selectedVersion.id, selectedContentNodeId, editorMarkdown, true);
      await refreshWorkspace(project.id, selectedNodeId);
      setSelectedContentNodeId(null);
      setNotice({ kind: "ok", text: `已把小节修改保存为 v${newVersion.version_no}` });
    });
  }

  async function handleSelectVersion(version: ChapterVersion) {
    if (!project || !selectedNodeId) return;
    await run(async () => {
      await selectVersion(project.id, selectedNodeId, version.id);
      setEditorMarkdown(version.markdown);
      setSelectedContentNodeId(null);
      await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: `已选择版本 v${version.version_no}` });
    });
  }

  async function handleChapterProposal() {
    if (!project || !selectedNodeId || !chapterSuggestion.trim()) return;
    await run(async () => {
      await proposeChapterEdit(project.id, selectedNodeId, chapterSuggestion.trim(), editorMarkdown);
      setChapterSuggestion("");
      await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: "已生成章节 AI 修改建议，确认后才会成为新版本" });
    });
  }

  async function handleApplyProposal(proposal: AIProposal) {
    if (!project) return;
    await run(async () => {
      if (proposal.target_type === "chapter") {
        if (!selectedNodeId) return;
        await applyChapterProposal(project.id, selectedNodeId, proposal.id);
        await refreshWorkspace(project.id, selectedNodeId);
      } else {
        await applyOutlineProposal(project.id, proposal.id);
        setOutlineAIProposal(null);
        await refreshDirectory(project.id);
      }
      setNotice({ kind: "ok", text: "修改建议已确认应用" });
    });
  }

  async function handleGenerateAll() {
    if (!project) return;
    await run(async () => {
      const runResult = await generateProject(project.id);
      await refreshDirectory(project.id);
      if (selectedNodeId) await refreshWorkspace(project.id, selectedNodeId);
      setNotice({ kind: "ok", text: `全量逐章生成完成：${runResult.passed_count}/${runResult.task_count}` });
    });
  }

  async function handleMerge() {
    if (!project) return;
    await run(async () => {
      await mergeProject(project.id);
      setFinalMarkdown(await getFinalMarkdown(project.id));
      setNotice({ kind: "ok", text: "已按每章选中版本合并 final.md" });
    });
  }

  function setSelectedNodePatch(patch: Partial<OutlineNode>) {
    if (!selectedNode) return;
    setOutlineNodes((items) => items.map((item) => (item.node_id === selectedNode.node_id ? { ...item, ...patch } : item)));
  }

  function handleSelectContentNode(node: GeneratedContentNode) {
    setSelectedContentNodeId(node.id);
    setEditorMarkdown(node.markdown);
    setNotice({ kind: "ok", text: `正在编辑正文小节：${node.title}` });
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>施工组织设计生成工作台</h1>
          <p className={notice.kind === "warn" ? "notice-warn" : ""}>{notice.text}</p>
        </div>
        <span className={busy ? "busy-pill" : "idle-pill"}>{busy ? "处理中" : "就绪"}</span>
      </header>

      <nav className="workflow-strip" aria-label="生成流程">
        {workflowSteps.map((step, index) => (
          <span key={step.label} className={step.done ? "workflow-step done" : "workflow-step"}>
            <b>{index + 1}</b>
            {step.label}
          </span>
        ))}
      </nav>

      <div className="workspace-grid">
        <aside className="rail">
          <section className="panel">
            <div className="panel-heading">
              <h2>项目</h2>
              <span>{projects.length}</span>
            </div>
            <label className="field">
              <span>模板</span>
              <select value={templateId} disabled={busy || Boolean(project)} onChange={(event) => setTemplateId(event.target.value)}>
                {templates.map((template) => (
                  <option key={template.template_id} value={template.template_id}>
                    {template.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>项目名称</span>
              <input value={projectName} disabled={busy || Boolean(project)} onChange={(event) => setProjectName(event.target.value)} />
            </label>
            <div className="button-row">
              <button disabled={busy || Boolean(project)} onClick={() => void handleCreateProject()}>
                创建
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  setProject(null);
                  setDirectory(null);
                  setOutlineNodes([]);
                  setWorkspace(null);
                  setSelectedNodeId(null);
                  setOutlineAIProposal(null);
                  setSelectedContentNodeId(null);
                }}
              >
                新建流程
              </button>
            </div>
            <div className="project-list">
              {projects.map((item) => (
                <button key={item.id} className={item.id === project?.id ? "selected" : ""} onClick={() => openProject(item)}>
                  <strong>{item.name}</strong>
                  <span>{item.section_count} 节来源 / {item.run_count} 次生成</span>
                </button>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <h2>输入</h2>
              <span>{project?.section_count ?? 0} 节</span>
            </div>
            <label className={`file-drop ${!project || busy ? "disabled" : ""}`}>
              上传投标 Markdown
              <input type="file" accept=".md,.markdown,text/plain" disabled={!project || busy} onChange={(event) => void handleUpload(event.currentTarget.files?.[0])} />
            </label>
            <div className="button-row">
              <button disabled={!project || busy || (project.section_count ?? 0) === 0} onClick={() => void handleGenerateDirectory()}>
                生成基础目录
              </button>
              <button disabled={!project || busy} onClick={() => void refreshDirectory().catch(showError)}>
                刷新
              </button>
            </div>
          </section>

          <section className="panel tree-panel">
            <div className="panel-heading">
              <h2>模板陈列</h2>
              <span>{countTemplateNodes(templateTree)}</span>
            </div>
            <div className="tree-scroll">
              {templateTree.map((node) => (
                <TemplateTreeItem key={node.id} node={node} />
              ))}
            </div>
          </section>
        </aside>

        <section className="panel directory-panel">
          <div className="panel-heading">
            <h2>项目目录与来源</h2>
            <span>{outlineNodes.length} 个节点 / {wordStats.withTarget} 个已设字数 / {wordStats.total} 字</span>
          </div>
          <div className="directory-layout">
            <div className="outline-list">
              {outlineNodes.map((node) => (
                <button
                  key={node.node_id}
                  className={node.node_id === selectedNodeId ? "selected outline-row" : "outline-row"}
                  style={{ paddingLeft: `${12 + Math.max(0, node.level - 1) * 14}px` }}
                  onClick={() => setSelectedNodeId(node.node_id)}
                >
                  <span>{node.enabled === false ? "停用" : "启用"}</span>
                  <strong>{node.title}</strong>
                  <small>{node.target_word_count ? `${node.target_word_count} 字` : "未设字数"}</small>
                </button>
              ))}
              {outlineNodes.length === 0 ? <p className="empty-text">生成目录后，这里会变成可编辑的项目目录树。</p> : null}
            </div>

            <div className="node-editor">
              {selectedNode ? (
                <>
                  <label className="field compact-field">
                    <span>章节标题</span>
                    <input value={selectedNode.title} onChange={(event) => setSelectedNodePatch({ title: event.target.value })} />
                  </label>
                  <div className="inline-fields">
                    <label className="check-field">
                      <input
                        type="checkbox"
                        checked={selectedNode.enabled !== false}
                        onChange={(event) => setSelectedNodePatch({ enabled: event.target.checked })}
                      />
                      启用
                    </label>
                    <label className="field compact-field">
                      <span>排序</span>
                      <input
                        type="number"
                        value={selectedNode.sort_order ?? 0}
                        onChange={(event) => setSelectedNodePatch({ sort_order: Number(event.target.value) })}
                      />
                    </label>
                    <label className="field compact-field">
                      <span>目标字数</span>
                      <input
                        type="number"
                        min={0}
                        step={50}
                        value={selectedNode.target_word_count ?? ""}
                        onChange={(event) => setSelectedNodePatch({ target_word_count: event.target.value ? Number(event.target.value) : null })}
                      />
                    </label>
                  </div>
                  <ModuleTextarea label="主要来源" values={selectedNode.source_rules} onChange={(values) => setSelectedNodePatch({ source_rules: values })} />
                  <ModuleTextarea label="自动补充" values={selectedNode.auto_fill} onChange={(values) => setSelectedNodePatch({ auto_fill: values })} />
                  <ModuleTextarea label="人工补充需补充" values={selectedNode.manual_fill} onChange={(values) => setSelectedNodePatch({ manual_fill: values })} />
                  <ModuleTextarea label="特殊备注" values={selectedNode.special_notes} onChange={(values) => setSelectedNodePatch({ special_notes: values })} />
                  <div className="button-row">
                    <button disabled={busy} onClick={() => void handleUpdateNode()}>保存节点</button>
                    <button disabled={busy} onClick={() => void handleDeleteNode()}>删除节点</button>
                  </div>
                  <div className="add-node">
                    <input placeholder="新增节点标题" value={newNodeTitle} onChange={(event) => setNewNodeTitle(event.target.value)} />
                    <button disabled={busy || !newNodeTitle.trim()} onClick={() => void handleCreateNode(selectedNode.node_id)}>加子章</button>
                    <button disabled={busy || !newNodeTitle.trim()} onClick={() => void handleCreateNode(selectedNode.parent_id ?? null)}>加同级</button>
                  </div>

                  <section className="subpanel">
                    <div className="mini-heading">
                      <strong>字数目标</strong>
                      <span>{wordStats.total || 0} 字</span>
                    </div>
                    <label className="file-drop tiny">
                      读取参考施组 Markdown
                      <input type="file" accept=".md,.markdown,text/plain" disabled={busy} onChange={(event) => void handleReferenceFile(event.currentTarget.files?.[0])} />
                    </label>
                    <label className="field compact-field">
                      <span>参考施组 Markdown</span>
                      <textarea value={referenceMarkdown} onChange={(event) => setReferenceMarkdown(event.target.value)} placeholder="可粘贴目标施组或历史生成文档 Markdown；留空则按章节类型给默认字数。" />
                    </label>
                    <button disabled={!project || busy} onClick={() => void handleEstimateWordCounts()}>估算并写回目录字数</button>
                  </section>

                  <section className="subpanel">
                    <div className="mini-heading">
                      <strong>AI 目录建议</strong>
                      <span>预览后应用</span>
                    </div>
                    <label className="field compact-field">
                      <span>调整建议</span>
                      <textarea value={outlineSuggestion} onChange={(event) => setOutlineSuggestion(event.target.value)} placeholder="例如：把安全文明施工拆成安全管理、环保水保、应急处置三个小节。" />
                    </label>
                    <div className="button-row no-pad">
                      <button disabled={!project || busy} onClick={() => void handleAIPlanOutline()}>AI 优化目录</button>
                      <button disabled={busy || !outlineSuggestion.trim()} onClick={() => void handleOutlineProposal()}>普通建议预览</button>
                    </div>
                    {outlineAIProposal ? (
                      <article className="inline-proposal">
                        <strong>AI 目录建议 / {outlineAIProposal.status}</strong>
                        <p>{outlineAIProposal.suggestion}</p>
                        <button disabled={busy} onClick={() => void handleApplyProposal(outlineAIProposal)}>应用 AI 目录建议</button>
                      </article>
                    ) : null}
                  </section>
                </>
              ) : (
                <p className="empty-text">选择一个目录节点后，可编辑四模块、排序、启停、字数目标和新增子章节。</p>
              )}
            </div>

            <div className="source-list">
              <h3>输入文档目录</h3>
              <SourceTocList items={sourceItems.slice(0, 120)} />
            </div>
          </div>
        </section>

        <section className="panel chapter-panel">
          <div className="panel-heading">
            <h2>章节工作区</h2>
            <span>{selectedNode?.title ?? "未选择"}</span>
          </div>
          <div className="chapter-layout">
            <div className="chapter-context">
              <h3>补充材料</h3>
              <div className="supplement-form">
                <select value={supplement.kind} onChange={(event) => setSupplement({ ...supplement, kind: event.target.value })}>
                  <option value="text">文本</option>
                  <option value="table">表格</option>
                  <option value="note">要求</option>
                </select>
                <input placeholder="标题" value={supplement.title} onChange={(event) => setSupplement({ ...supplement, title: event.target.value })} />
                <textarea placeholder="补充内容，将进入单章生成 prompt" value={supplement.content} onChange={(event) => setSupplement({ ...supplement, content: event.target.value })} />
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={supplement.must_include}
                    onChange={(event) => setSupplement({ ...supplement, must_include: event.target.checked })}
                  />
                  必须写入正文
                </label>
                <button disabled={!project || !selectedNodeId || busy || !supplement.title.trim() || !supplement.content.trim()} onClick={() => void handleAddSupplement()}>
                  保存补充材料
                </button>
              </div>
              <SavedSupplements items={workspace?.supplements ?? []} />

              <h3>附件说明</h3>
              <input placeholder="附件说明会进入 prompt；第一版不做视觉识别" value={attachmentDescription} onChange={(event) => setAttachmentDescription(event.target.value)} />
              <label className={`file-drop small ${!selectedNodeId || busy ? "disabled" : ""}`}>
                上传附件
                <input type="file" disabled={!selectedNodeId || busy} onChange={(event) => void handleAttachment(event.currentTarget.files?.[0])} />
              </label>
              <div className="attachment-list">
                {(workspace?.attachments ?? []).map((attachment) => (
                  <article key={attachment.id}>
                    <strong>{attachment.file_name}</strong>
                    <span>{attachment.description || "无说明"}</span>
                  </article>
                ))}
              </div>
            </div>

            <div className="markdown-editor">
              <div className="button-row sticky-actions">
                <button disabled={!selectedNodeId || busy} onClick={() => void handleGenerateChapter()}>生成当前章</button>
                <button disabled={!selectedNodeId || busy} onClick={() => void handleSaveManualVersion()}>保存为新版本</button>
                <button disabled={!selectedContentNodeId || busy} onClick={() => void handleSaveContentNode()}>保存小节为新版本</button>
                <button disabled={!project || busy || outlineNodes.length === 0} onClick={() => void handleGenerateAll()}>全量逐章生成</button>
                <button disabled={!project || busy || outlineNodes.length === 0} onClick={() => void handleMerge()}>合并选中版本</button>
              </div>
              {selectedContentNode ? <p className="edit-hint">正在编辑正文小节：{selectedContentNode.title}</p> : null}
              <textarea value={editorMarkdown} onChange={(event) => setEditorMarkdown(event.target.value)} />
            </div>

            <div className="version-panel">
              <h3>版本</h3>
              <div className="version-list">
                {(workspace?.versions ?? []).map((version) => (
                  <button
                    key={version.id}
                    className={version.id === workspace?.selected_version_id ? "selected" : ""}
                    onClick={() => void handleSelectVersion(version)}
                  >
                    <strong>v{version.version_no} / {version.source_type}</strong>
                    <span>{version.status}</span>
                  </button>
                ))}
                {!workspace?.versions.length ? <p className="empty-text">生成或手动保存后会出现版本。</p> : null}
              </div>
              <p className="selected-version">{selectedVersion ? `当前选中：v${selectedVersion.version_no}` : "当前无选中版本"}</p>

              <h3>正文小节树</h3>
              <ContentTreeList nodes={contentNodes} selectedId={selectedContentNodeId} onSelect={handleSelectContentNode} />

              <label className="field compact-field">
                <span>让 AI 修改当前版本</span>
                <textarea value={chapterSuggestion} onChange={(event) => setChapterSuggestion(event.target.value)} placeholder="例如：补充安全措施，语气更像正式施组文件。" />
              </label>
              <button disabled={!selectedNodeId || busy || !chapterSuggestion.trim()} onClick={() => void handleChapterProposal()}>生成修改建议</button>
              <ProposalList proposals={workspace?.proposals ?? []} onApply={(proposal) => void handleApplyProposal(proposal)} />
            </div>
          </div>
        </section>

        <section className="panel final-panel">
          <div className="panel-heading">
            <h2>最终合并 Markdown</h2>
            <span>{finalMarkdown ? "已生成" : "待合并"}</span>
          </div>
          <pre>{finalMarkdown || "合并时只读取每个章节当前选中的版本。"}</pre>
        </section>
      </div>
    </main>
  );
}

function TemplateTreeItem({ node }: { node: TemplateNode }) {
  return (
    <div className="tree-node" style={{ paddingLeft: `${Math.max(0, node.level - 1) * 12}px` }}>
      <span>{node.title}</span>
      {node.children.map((child) => (
        <TemplateTreeItem key={child.id} node={child} />
      ))}
    </div>
  );
}

function ModuleTextarea({ label, values, onChange }: { label: string; values: string[]; onChange: (values: string[]) => void }) {
  return (
    <label className="field compact-field">
      <span>{label}</span>
      <textarea value={(values ?? []).join("\n")} onChange={(event) => onChange(lines(event.target.value))} />
    </label>
  );
}

function SourceTocList({ items }: { items: SourceTocItem[] }) {
  return (
    <div className="toc-list">
      {items.map((item) => (
        <article key={item.section_id} style={{ marginLeft: `${Math.max(0, item.level - 1) * 8}px` }}>
          <strong>{item.title_path.join(" > ")}</strong>
          <span>{item.section_id} / {item.char_count} 字</span>
          <p>{item.snippet}</p>
        </article>
      ))}
      {items.length === 0 ? <p className="empty-text">暂无来源目录。</p> : null}
    </div>
  );
}

function SavedSupplements({ items }: { items: ChapterSupplement[] }) {
  return (
    <div className="saved-list">
      {items.map((item) => (
        <article key={item.id}>
          <strong>{item.title}</strong>
          <span>{item.kind} / {item.must_include ? "必须写入" : "参考"}</span>
          <p>{item.content}</p>
        </article>
      ))}
      {items.length === 0 ? <p className="empty-text">暂无补充材料。</p> : null}
    </div>
  );
}

function ContentTreeList({
  nodes,
  selectedId,
  onSelect
}: {
  nodes: GeneratedContentNode[];
  selectedId: string | null;
  onSelect: (node: GeneratedContentNode) => void;
}) {
  if (!nodes.length) return <p className="empty-text">生成章节后会显示正文小节树。</p>;
  return (
    <div className="content-node-list">
      {nodes.map((node) => (
        <button
          key={node.id}
          className={node.id === selectedId ? "selected content-node-row" : "content-node-row"}
          style={{ paddingLeft: `${8 + Math.max(0, node.level - 1) * 10}px` }}
          onClick={() => onSelect(node)}
        >
          <strong>{node.title}</strong>
          <span>{node.source_links.length} 个来源 / {node.start_line}-{node.end_line} 行</span>
        </button>
      ))}
    </div>
  );
}

function ProposalList({ proposals, onApply }: { proposals: AIProposal[]; onApply: (proposal: AIProposal) => void }) {
  return (
    <div className="proposal-list">
      {proposals.map((proposal) => (
        <article key={proposal.id}>
          <strong>{proposal.target_type} / {proposal.status}</strong>
          <p>{proposal.suggestion}</p>
          {proposal.status === "pending" ? <button onClick={() => onApply(proposal)}>确认应用</button> : null}
        </article>
      ))}
    </div>
  );
}

function lines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function countTemplateNodes(nodes: TemplateNode[]): number {
  return nodes.reduce((total, node) => total + 1 + countTemplateNodes(node.children), 0);
}

function flattenContentNodes(nodes: GeneratedContentNode[]): GeneratedContentNode[] {
  return nodes.flatMap((node) => [node, ...flattenContentNodes(node.children ?? [])]);
}
