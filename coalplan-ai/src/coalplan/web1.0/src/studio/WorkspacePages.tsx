import { useState } from "react";
import {
  ArrowRight,
  Plus,
  Upload,
  FileText,
  Download,
  CheckCircle2,
} from "lucide-react";
import * as A from "@/lib/api";
import { useToast } from "@/components/Toast";
import { useJobs } from "@/components/Jobs";
import { ReviewResults } from "./Rules";
import {
  Modal,
  Filter,
  Status,
  useResource,
  Document,
  download,
  api,
} from "./common";

export function Projects({
  select,
}: {
  select: (p: A.ProjectResponse) => void;
}) {
  const projects = useResource(A.listProjects, []),
    templates = useResource(A.listTemplates, []),
    [query, setQuery] = useState(""),
    [create, setCreate] = useState(false),
    [name, setName] = useState(""),
    [template, setTemplate] = useState(""),
    [busy, setBusy] = useState(false);
  const toast = useToast();
  const submit = async () => {
    setBusy(true);
    try {
      const p = await A.createProject(
        name,
        template || templates.data?.[0]?.template_id || "",
      );
      setCreate(false);
      select(p);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="s-toolbar">
        <Filter value={query} change={setQuery} placeholder="搜索项目名称" />
        <button className="primary" onClick={() => setCreate(true)}>
          <Plus size={17} />
          新建项目
        </button>
      </div>
      <Status {...projects} retry={projects.reload} />
      <div className="s-project-grid">
        {projects.data
          ?.filter((p) => p.name.includes(query))
          .map((p) => (
            <article className="s-project" key={p.project_id}>
              <div className="s-project-top">
                <span className="s-file-icon">
                  <FileText size={21} />
                </span>
                <span className="s-badge">
                  {p.section_count ? "资料已入库" : "待上传资料"}
                </span>
              </div>
              <h2>{p.name}</h2>
              <p>
                {p.source_document_count} 份资料 <span>·</span>{" "}
                {p.section_count} 个来源章节
              </p>
              <button onClick={() => select(p)}>
                进入工作台
                <ArrowRight size={16} />
              </button>
            </article>
          ))}
      </div>
      {projects.data?.length === 0 && (
        <div className="s-empty">暂无项目，创建第一个工程项目。</div>
      )}
      {create && (
        <Modal title="新建工程项目" close={() => setCreate(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label>
              项目名称
              <input
                autoFocus
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="输入工程项目名称"
              />
            </label>
            <label>
              初始模板
              <select
                value={template || templates.data?.[0]?.template_id || ""}
                onChange={(e) => setTemplate(e.target.value)}
              >
                {templates.data?.map((t) => (
                  <option key={t.template_id} value={t.template_id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="s-dialog-actions">
              <button type="button" onClick={() => setCreate(false)}>
                取消
              </button>
              <button
                className="primary"
                disabled={busy || !name.trim() || !templates.data?.length}
              >
                {busy ? "创建中…" : "创建项目"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
export function Sources({
  project,
  next,
}: {
  project: A.ProjectResponse;
  next: () => void;
}) {
  const documents = useResource(
      () => A.listProjectSourceDocuments(project.project_id),
      [project.project_id],
    ),
    memories = useResource(
      () => A.listProjectMemories(project.project_id),
      [project.project_id],
    ),
    [files, setFiles] = useState<{ name: string; state: string }[]>([]),
    [source, setSource] = useState<A.SourceSection | null>(null),
    [directory, setDirectory] = useState<A.SourceTocItem[] | null>(null),
    [memory, setMemory] = useState(false),
    [topic, setTopic] = useState(""),
    [content, setContent] = useState(""),
    [busy, setBusy] = useState(false);
  const toast = useToast();
  const upload = async (list: FileList | null) => {
    if (!list) return;
    setBusy(true);
    const items = Array.from(list);
    setFiles(items.map((f) => ({ name: f.name, state: "等待上传" })));
    for (let i = 0; i < items.length; i++) {
      setFiles((v) =>
        v.map((x, j) => (j === i ? { ...x, state: "读取与切章中" } : x)),
      );
      try {
        await api(`/projects/${project.project_id}/bid-markdown`, {
          file_name: items[i].name,
          content: await items[i].text(),
          append: true,
        });
        setFiles((v) =>
          v.map((x, j) => (j === i ? { ...x, state: "已入库" } : x)),
        );
      } catch (e) {
        setFiles((v) =>
          v.map((x, j) =>
            j === i ? { ...x, state: (e as Error).message } : x,
          ),
        );
      }
      documents.reload();
    }
    setBusy(false);
  };
  const browse = async (documentId: string) => {
    try {
      setDirectory(
        await api<A.SourceTocItem[]>(
          `/projects/${project.project_id}/source-documents/${documentId}/sections`,
        ),
      );
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <>
      <div className="s-toolbar">
        <span className="s-subtitle">当前投标资料决定项目事实</span>
        <div className="s-actions">
          <label className="s-upload-button">
            <Upload size={16} />
            上传 Markdown
            <input
              type="file"
              accept=".md"
              multiple
              disabled={busy}
              onChange={(e) => void upload(e.target.files)}
            />
          </label>
          <button className="primary" onClick={next}>
            规划目录
            <ArrowRight size={16} />
          </button>
        </div>
      </div>
      <Status {...documents} retry={documents.reload} />
      {files.map((f, i) => (
        <p role="status" className="s-file-status" key={i}>
          {f.name}
          <span>{f.state}</span>
        </p>
      ))}
      <div className="s-table-wrap">
        <table>
          <thead>
            <tr>
              <th>资料名称</th>
              <th>章节</th>
              <th>内容量</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {documents.data?.map((d) => (
              <tr key={d.id}>
                <td>
                  <FileText size={16} />
                  {d.file_name}
                </td>
                <td>{d.section_count}</td>
                <td>{d.character_count.toLocaleString()} 字符</td>
                <td>
                  <button onClick={() => void browse(d.id)}>查阅来源</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section className="s-band">
        <div className="s-toolbar">
          <h2>项目补充信息</h2>
          <button onClick={() => setMemory(true)}>
            <Plus size={16} />
            补充信息
          </button>
        </div>
        <Status {...memories} retry={memories.reload} />
        {memories.data?.length ? (
          memories.data.map((m) => (
            <details key={m.memory_id}>
              <summary>{m.topic}</summary>
              <p className="s-pre">{m.content}</p>
            </details>
          ))
        ) : (
          <p className="s-muted">暂无补充信息</p>
        )}
      </section>
      {memory && (
        <Modal title="保存项目补充信息" close={() => setMemory(false)}>
          <label>
            事项名称
            <input value={topic} onChange={(e) => setTopic(e.target.value)} />
          </label>
          <label>
            已确认的信息
            <textarea
              rows={6}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </label>
          <div className="s-dialog-actions">
            <button
              className="primary"
              disabled={busy || !topic.trim() || !content.trim()}
              onClick={async () => {
                setBusy(true);
                try {
                  await A.addProjectMemory(project.project_id, {
                    topic,
                    content,
                  });
                  setMemory(false);
                  memories.reload();
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              保存到项目
            </button>
          </div>
        </Modal>
      )}
      {directory && (
        <Modal title="投标来源目录" close={() => setDirectory(null)}>
          {directory.map((s) => (
            <button
              className="s-list-row"
              key={s.section_id}
              onClick={async () => {
                try {
                  setSource(
                    await A.getSourceSection(project.project_id, s.section_id),
                  );
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              {s.title_path.join(" / ")}
            </button>
          ))}
        </Modal>
      )}
      {source && (
        <Modal
          wide
          title={source.title_path.join(" / ")}
          close={() => setSource(null)}
        >
          <p className="s-muted">{source.source_file}</p>
          <Document text={source.content} />
        </Modal>
      )}
    </>
  );
}
export function Delivery({ project }: { project: A.ProjectResponse }) {
  const summary = useResource(
      () => A.getProjectExperienceSummary(project.project_id),
      [project.project_id],
    ),
    { activeJob, startJob } = useJobs(),
    [preview, setPreview] = useState(""),
    [busy, setBusy] = useState(false);
  const toast = useToast();
  const read = async () => {
    const r = await fetch(
      `${A.API_BASE}/projects/${project.project_id}/artifacts/current.md`,
    );
    if (!r.ok)
      throw new Error("目前没有可导出的正文，请先生成并选用章节版本。");
    return r.text();
  };
  return (
    <>
      <Status {...summary} retry={summary.reload} />
      <div className="s-delivery">
        <CheckCircle2 size={30} />
        <div>
          <h2>当前选用的章节版本</h2>
          <p>{summary.data?.headline || "检查当前成稿状态"}</p>
        </div>
        <button
          className="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              download(await read(), `${project.name}.md`);
            } catch (e) {
              toast.error((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Download size={17} />
          导出当前 Markdown
        </button>
      </div>
      <div className="s-toolbar">
        <div className="s-actions">
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                setPreview(await read());
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            预览阶段稿
          </button>
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await A.mergeProject(project.project_id);
                setPreview(await read());
                toast.success("已合并选用版本");
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            合并选用版本
          </button>
        </div>
        <button
          disabled={Boolean(activeJob)}
          onClick={async () => {
            try {
              await startJob("compliance_review");
            } catch (e) {
              toast.error((e as Error).message);
            }
          }}
        >
          开始规范审查
        </button>
      </div>
      <p className="s-muted">
        阶段稿可导出；未完成章节、计算书及外部附件不视为已满足。
      </p>
      <ReviewResults projectId={project.project_id} />
      {preview && <Document text={preview} />}
    </>
  );
}
