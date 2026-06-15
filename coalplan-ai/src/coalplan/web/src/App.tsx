import { useEffect, useMemo, useState } from "react";
import {
  createProject,
  generateChapter,
  generateDirectory,
  generateProject,
  getChapter,
  getDirectory,
  getFinalMarkdown,
  getTemplateTree,
  listTemplates,
  mergeProject,
  uploadBidMarkdown,
  type ChapterResponse,
  type ChapterTask,
  type DirectoryResponse,
  type ProjectResponse,
  type SourceMatch,
  type SourceTocItem,
  type TemplateNode,
  type TemplateSummary
} from "./api";

export default function App() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateId, setTemplateId] = useState("coal_fire");
  const [templateTree, setTemplateTree] = useState<TemplateNode[]>([]);
  const [projectName, setProjectName] = useState("宁夏煤火北一火区演示");
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [directory, setDirectory] = useState<DirectoryResponse | null>(null);
  const [tasks, setTasks] = useState<ChapterTask[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [chapter, setChapter] = useState<ChapterResponse | null>(null);
  const [finalMarkdown, setFinalMarkdown] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("后端默认地址：http://127.0.0.1:8010");

  useEffect(() => {
    void listTemplates()
      .then((items) => {
        setTemplates(items);
        if (items[0]) setTemplateId(items[0].template_id);
      })
      .catch((error) => setNotice(error.message));
  }, []);

  useEffect(() => {
    if (!templateId) return;
    void getTemplateTree(templateId).then(setTemplateTree).catch((error) => setNotice(error.message));
  }, [templateId]);

  const selectedTask = useMemo(() => tasks.find((task) => task.node_id === selectedNodeId) ?? null, [tasks, selectedNodeId]);
  const tocItems = directory?.source_toc?.items ?? [];

  async function withBusy(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateProject() {
    await withBusy(async () => {
      const created = await createProject(projectName.trim() || "施工组织设计演示", templateId);
      setProject(created);
      setDirectory(null);
      setTasks([]);
      setChapter(null);
      setFinalMarkdown("");
      setNotice(`已创建项目：${created.name}`);
    });
  }

  async function handleUpload(file?: File | null) {
    if (!project || !file) return;
    await withBusy(async () => {
      const content = await file.text();
      const updated = await uploadBidMarkdown(project.id, file.name, content);
      setProject(updated);
      setDirectory(null);
      setTasks([]);
      setNotice(`已上传并切分：${updated.section_count} 个来源章节`);
    });
  }

  async function handleGenerateDirectory() {
    if (!project) return;
    await withBusy(async () => {
      const data = await generateDirectory(project.id);
      setDirectory(data);
      setProject(data.project);
      setTasks(data.chapter_tasks);
      setTemplateTree(data.template?.nodes ?? templateTree);
      setNotice(`目录已生成：${data.source_toc?.items.length ?? 0} 个来源章节，${data.chapter_tasks.length} 个待生成小章节`);
    });
  }

  async function handleRefreshDirectory() {
    if (!project) return;
    await withBusy(async () => {
      const data = await getDirectory(project.id);
      setDirectory(data);
      setTasks(data.chapter_tasks);
      setNotice("目录已刷新");
    });
  }

  async function handleSelectTask(task: ChapterTask) {
    setSelectedNodeId(task.node_id);
    setChapter(null);
    if (!project || !task.draft_id) {
      return;
    }
    await withBusy(async () => {
      setChapter(await getChapter(project.id, task.node_id));
    });
  }

  async function handleGenerateSelected() {
    if (!project || !selectedNodeId) return;
    await withBusy(async () => {
      const generated = await generateChapter(project.id, selectedNodeId);
      setChapter(generated);
      const refreshed = await getDirectory(project.id);
      setDirectory(refreshed);
      setTasks(refreshed.chapter_tasks);
      setNotice(`已生成章节：${generated.title}`);
    });
  }

  async function handleGenerateAll() {
    if (!project) return;
    await withBusy(async () => {
      const run = await generateProject(project.id);
      setNotice(`全量生成完成：${run.status}`);
      const refreshed = await getDirectory(project.id);
      setDirectory(refreshed);
      setTasks(refreshed.chapter_tasks);
    });
  }

  async function handleMerge() {
    if (!project) return;
    await withBusy(async () => {
      const run = await mergeProject(project.id);
      setNotice(`合并状态：${run.status}`);
      if (run.final_artifact_path) {
        setFinalMarkdown(await getFinalMarkdown(project.id));
      }
    });
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>施工组织设计生成流程演示</h1>
          <p>{notice}</p>
        </div>
        <span className={busy ? "busy-pill" : "idle-pill"}>{busy ? "处理中" : "就绪"}</span>
      </header>

      <div className="workspace">
        <aside className="left-column">
          <section className="panel">
            <div className="panel-heading">
              <h2>1. 模板与输入</h2>
              <span className="status">{templates.length} 个模板</span>
            </div>
            <div className="form-body">
              <label className="field">
                <span>选择模板</span>
                <select disabled={busy || Boolean(project)} value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
                  {templates.map((template) => (
                    <option key={template.template_id} value={template.template_id}>
                      {template.name}（{template.template_id}）
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>项目名称</span>
                <input disabled={busy || Boolean(project)} value={projectName} onChange={(event) => setProjectName(event.target.value)} />
              </label>
              <div className="actions">
                <button disabled={busy || Boolean(project)} onClick={() => void handleCreateProject()}>
                  创建项目
                </button>
                <label className={`file-button ${!project || busy ? "disabled" : ""}`}>
                  上传投标 Markdown
                  <input
                    type="file"
                    accept=".md,.markdown,text/markdown,text/plain"
                    disabled={!project || busy}
                    onChange={(event) => void handleUpload(event.currentTarget.files?.[0])}
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="panel tree-panel">
            <div className="panel-heading">
              <h2>模板目录</h2>
              <span className="status">{countNodes(templateTree)} 节点</span>
            </div>
            <div className="tree-scroll">
              {templateTree.map((node) => (
                <TemplateTreeItem key={node.id} node={node} />
              ))}
            </div>
          </section>
        </aside>

        <section className="middle-column">
          <section className="panel">
            <div className="panel-heading">
              <h2>2. 生成并查看目录</h2>
              <span className="status">{tocItems.length} 来源章节</span>
            </div>
            <div className="actions compact">
              <button disabled={!project || busy || project.section_count === 0} onClick={() => void handleGenerateDirectory()}>
                生成目录
              </button>
              <button disabled={!project || busy} onClick={() => void handleRefreshDirectory()}>
                刷新目录
              </button>
              <button disabled={!project || busy || tasks.length === 0} onClick={() => void handleGenerateAll()}>
                全量逐章生成
              </button>
              <button disabled={!project || busy || tasks.length === 0} onClick={() => void handleMerge()}>
                合并
              </button>
            </div>
            <div className="split-list">
              <div>
                <h3>来源文档目录</h3>
                <SourceTocList items={tocItems.slice(0, 160)} />
              </div>
              <div>
                <h3>待生成小章节</h3>
                <div className="task-list">
                  {tasks.map((task) => (
                    <button
                      key={task.node_id}
                      className={task.node_id === selectedNodeId ? "selected task-button" : "task-button"}
                      onClick={() => void handleSelectTask(task)}
                    >
                      <span>{task.title}</span>
                      <em>{task.status}</em>
                    </button>
                  ))}
                  {tasks.length === 0 ? <p className="empty-text">上传文档后点击“生成目录”。</p> : null}
                </div>
              </div>
            </div>
          </section>
        </section>

        <aside className="right-column">
          <section className="panel preview-panel">
            <div className="panel-heading">
              <h2>3. 逐章生成</h2>
              <span className="status">{selectedTask?.title ?? "未选择"}</span>
            </div>
            <div className="actions compact">
              <button disabled={!selectedNodeId || busy} onClick={() => void handleGenerateSelected()}>
                生成当前章节
              </button>
            </div>
            <SourceMatches matches={chapter?.source_matches ?? selectedTask?.source_matches ?? []} />
            <pre className="markdown-preview chapter">{chapter?.markdown || "选择一个待生成小章节后，可单独生成并查看结果。"}</pre>
          </section>

          <section className="panel final-panel">
            <div className="panel-heading">
              <h2>最终合并结果</h2>
              <span className="status">{finalMarkdown ? "已生成" : "未合并"}</span>
            </div>
            <pre className="markdown-preview final">{finalMarkdown || "所有章节通过后点击“合并”。"}</pre>
          </section>
        </aside>
      </div>
    </main>
  );
}

function TemplateTreeItem({ node }: { node: TemplateNode }) {
  return (
    <div className="tree-node" style={{ paddingLeft: `${Math.max(0, node.level - 1) * 12}px` }}>
      <div className="tree-label">
        <span className="tree-title">{node.title}</span>
        {node.special_notes.length > 0 ? <span className="badge">重点</span> : null}
      </div>
      {node.children.map((child) => (
        <TemplateTreeItem key={child.id} node={child} />
      ))}
    </div>
  );
}

function SourceTocList({ items }: { items: SourceTocItem[] }) {
  return (
    <div className="toc-list">
      {items.map((item) => (
        <article key={item.section_id} className="toc-item" style={{ marginLeft: `${Math.max(0, item.level - 1) * 8}px` }}>
          <strong>{item.title_path.join(" > ")}</strong>
          <span>{item.section_id}</span>
          <p>{item.snippet}</p>
        </article>
      ))}
      {items.length === 0 ? <p className="empty-text">暂无来源目录。</p> : null}
    </div>
  );
}

function SourceMatches({ matches }: { matches: SourceMatch[] }) {
  return (
    <div className="source-strip">
      <h3>已映射来源</h3>
      {matches.length > 0 ? (
        matches.map((match) => (
          <article key={match.section_id} className="source-item">
            <strong>{match.title_path.join(" > ")}</strong>
            <p>{match.snippet}</p>
          </article>
        ))
      ) : (
        <p className="empty-text">生成当前章节后显示对应来源。</p>
      )}
    </div>
  );
}

function countNodes(nodes: TemplateNode[]): number {
  return nodes.reduce((total, node) => total + 1 + countNodes(node.children), 0);
}
