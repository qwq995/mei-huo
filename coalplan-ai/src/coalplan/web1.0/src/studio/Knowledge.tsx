import { useEffect, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Upload,
  FileText,
} from "lucide-react";
import * as A from "@/lib/api";
import { useToast } from "@/components/Toast";
import {
  api,
  Document,
  Filter,
  Modal,
  Status,
  statusName,
  useResource,
} from "./common";

type Atom = A.ReferenceAtomDetail & {
  schema_version?: string;
  parameterized_template?: string;
  publication_blockers?: string[];
  chapter_module?: string;
  process_family?: string;
  parameter_slots?: { name: string; value?: string; description?: string }[];
};
type AtomPage = { items: Atom[]; total: number; has_more: boolean };
export function AtomBrowser({
  published = false,
  selected = [],
  onSelect,
  documentId = "",
}: {
  published?: boolean;
  selected?: string[];
  onSelect?: (ids: string[]) => void;
  documentId?: string;
}) {
  const [input, setInput] = useState(""),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState(published ? "published" : ""),
    [page, setPage] = useState(1),
    [atom, setAtom] = useState<Atom | null>(null),
    [checked, setChecked] = useState<string[]>([]),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(input);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [input]);
  const result = useResource(
      () =>
        api<AtomPage>(
          `/reference-library/atoms/search?query=${encodeURIComponent(query)}&page=${page}&page_size=20${status ? `&status=${status}` : ""}${documentId ? `&document_id=${encodeURIComponent(documentId)}` : ""}`,
        ),
      [query, status, page, documentId],
    ),
    toast = useToast();
  const selection = onSelect ? selected : checked,
    select = onSelect || setChecked;
  const toggle = (id: string) =>
    select(
      selection.includes(id)
        ? selection.filter((x) => x !== id)
        : [...selection, id],
    );
  const publish = async () => {
    setBusy(true);
    try {
      const r = await api<{ published_count?: number; blocked?: unknown[] }>(
        "/reference-library/atoms/bulk-publish",
        { atom_ids: checked },
      );
      toast.success(
        `发布操作完成，请核对条目状态${r.blocked?.length ? `；${r.blocked.length} 条未通过` : ""}`,
      );
      setChecked([]);
      result.reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="s-atom-browser">
      <div className="s-toolbar">
        <Filter
          value={input}
          change={setInput}
          placeholder="搜索工艺、模块或原子正文"
        />
        {!published && (
          <select
            aria-label="原子状态"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
              setChecked([]);
            }}
          >
            <option value="">全部状态</option>
            {["pending_publish", "published", "ai_candidate", "rejected"].map(
              (s) => (
                <option key={s} value={s}>
                  {statusName(s)}
                </option>
              ),
            )}
          </select>
        )}
        {!onSelect && (
          <button
            className="primary"
            disabled={busy || !checked.length}
            onClick={() => void publish()}
          >
            <Check size={15} />
            发布已选 {checked.length || ""}
          </button>
        )}
      </div>
      <Status {...result} retry={result.reload} />
      <div className="s-atom-list">
        {result.data?.items.map((a) => (
          <div key={a.id} className="s-atom-row">
            <input
              type="checkbox"
              aria-label={`选择 ${a.title_path[a.title_path.length - 1] || a.id}`}
              checked={selection.includes(a.id)}
              onChange={() => toggle(a.id)}
            />
            <button className="s-atom-content" onClick={() => setAtom(a)}>
              <strong>
                {a.title_path[a.title_path.length - 1] ||
                  a.process ||
                  "原子正文"}
              </strong>
              <p>{a.parameterized_template || a.content}</p>
              <small>
                {a.project_name} ·{" "}
                {a.process_family || a.process || a.chapter_type}
              </small>
            </button>
            <span
              className={`s-badge ${a.status === "published" ? "green" : ""}`}
            >
              {statusName(a.status)}
            </span>
          </div>
        ))}
      </div>
      {!result.loading && result.data?.total === 0 && (
        <p className="s-empty">没有匹配的原子，请调整搜索条件。</p>
      )}
      <div className="s-pagination">
        <span>
          共 {result.data?.total ?? 0} 条 · 第 {page} 页
        </span>
        <div>
          <button
            className="s-icon"
            aria-label="上一页"
            disabled={page === 1 || result.loading}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            className="s-icon"
            aria-label="下一页"
            disabled={!result.data?.has_more || result.loading}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      {atom && (
        <Modal
          wide
          title={atom.title_path.join(" / ")}
          close={() => setAtom(null)}
        >
          <div className="s-toolbar">
            <span>
              {atom.project_name} · {statusName(atom.status)}
            </span>
            <span className="s-badge">{atom.schema_version || "历史格式"}</span>
          </div>
          <h3>可复用内容</h3>
          <Document text={atom.parameterized_template || atom.content} />
          <div className="s-form-grid">
            <section>
              <h3>适用边界</h3>
              <p>{atom.applicability?.join("；") || "未标注"}</p>
              <h3>禁止套用场景</h3>
              <p>{atom.prohibited_scenarios?.join("；") || "未标注"}</p>
            </section>
            <section>
              <h3>工艺与内容标签</h3>
              <p>
                {[
                  atom.process_family,
                  atom.process,
                  atom.chapter_module,
                  atom.chapter_type,
                  ...(atom.content_functions || []),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <h3>参数与项目变量</h3>
              {atom.fact_variables?.map((v, i) => (
                <p key={i}>
                  {v.name}：{v.value}（{v.migration_policy}）
                </p>
              ))}
            </section>
          </div>
          {atom.publication_blockers?.length ? (
            <div className="s-alert">
              {atom.publication_blockers.join("；")}
            </div>
          ) : null}
          <details>
            <summary>原始正文与来源位置</summary>
            <p>
              原文第 {atom.start_line}–{atom.end_line} 行
            </p>
            <Document text={atom.content} />
            <small>{atom.id}</small>
          </details>
          <div className="s-dialog-actions">
            {onSelect ? (
              <button
                className="primary"
                onClick={() => {
                  toggle(atom.id);
                  setAtom(null);
                }}
              >
                {selected.includes(atom.id) ? "取消固定" : "固定到本章"}
              </button>
            ) : (
              <button
                className="danger"
                disabled={busy}
                onClick={async () => {
                  if (
                    !confirm(
                      "排除此原子后，它将不再进入新生成的候选。历史使用记录保留。",
                    )
                  )
                    return;
                  setBusy(true);
                  try {
                    await A.updateReferenceAtomStatus(atom.id, "rejected");
                    setAtom(null);
                    result.reload();
                  } catch (e) {
                    toast.error((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                排除此原子
              </button>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
export function Knowledge({ view }: { view: string }) {
  const docs = useResource(
      () =>
        api<
          {
            id: string;
            file_name: string;
            project_name: string;
            project_type: string;
          }[]
        >("/reference-library/documents"),
      [],
    ),
    templates = useResource(A.listOutlineTemplates, []),
    projects = useResource(A.listProjects, []),
    [query, setQuery] = useState(""),
    [doc, setDoc] = useState(""),
    [template, setTemplate] = useState<A.OutlineTemplateDocument | null>(null),
    [upload, setUpload] = useState(false),
    [files, setFiles] = useState<File[]>([]),
    [projectId, setProjectId] = useState(""),
    [busy, setBusy] = useState(false),
    [job, setJob] = useState<A.GenerationJob | null>(null);
  const toast = useToast();
  useEffect(() => {
    const saved = localStorage.getItem("studio:import-job");
    if (saved) {
      const { project_id, job_id } = JSON.parse(saved);
      A.getGenerationJob(project_id, job_id)
        .then(setJob)
        .catch(() => {});
    }
  }, []);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = setInterval(
      () =>
        A.getGenerationJob(job.project_id, job.job_id)
          .then((next) => {
            setJob(next);
            if (!["queued", "running"].includes(next.status)) docs.reload();
          })
          .catch(() => {}),
      2000,
    );
    return () => clearInterval(timer);
  }, [job?.job_id, job?.status]);
  return (
    <>
      {view === "atoms" ? (
        <AtomBrowser />
      ) : view === "documents" ? (
        <>
          <div className="s-toolbar">
            <Filter
              value={query}
              change={setQuery}
              placeholder="搜索参考文档"
            />
            <button className="primary" onClick={() => setUpload(true)}>
              <Upload size={16} />
              批量导入并切分
            </button>
          </div>
          {job && (
            <div className="s-notice">
              <span>
                {statusName(job.status)} · {job.message} {job.current}/
                {job.total}
              </span>
              {["failed", "partial", "interrupted"].includes(job.status) && (
                <button
                  onClick={async () => {
                    try {
                      setJob(
                        await A.retryGenerationJob(job.project_id, job.job_id),
                      );
                    } catch (e) {
                      toast.error((e as Error).message);
                    }
                  }}
                >
                  重试
                </button>
              )}
            </div>
          )}
          <Status {...docs} retry={docs.reload} />
          <div className="s-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文档名称</th>
                  <th>来源项目</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {docs.data
                  ?.filter((d) =>
                    (d.file_name + d.project_name).includes(query),
                  )
                  .map((d) => (
                    <tr key={d.id}>
                      <td>
                        <FileText size={16} />
                        {d.file_name}
                      </td>
                      <td>{d.project_name}</td>
                      <td>
                        <button onClick={() => setDoc(d.id)}>查看原子</button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <div className="s-toolbar">
            <Filter
              value={query}
              change={setQuery}
              placeholder="搜索模板名称或标签"
            />
            <span className="s-badge">
              {templates.data?.length ?? 0} 个模板
            </span>
          </div>
          <Status {...templates} retry={templates.reload} />
          {templates.data
            ?.filter((t) => (t.project_name + t.tags.join(" ")).includes(query))
            .map((t) => (
              <button
                className="s-list-row"
                key={t.template_id}
                onClick={async () => {
                  try {
                    setTemplate(await A.getOutlineTemplate(t.template_id));
                  } catch (e) {
                    toast.error((e as Error).message);
                  }
                }}
              >
                <span>
                  {t.project_name}
                  <small>{t.tags.join(" · ")}</small>
                </span>
                <span>
                  {t.title_count} 节<ChevronRight size={16} />
                </span>
              </button>
            ))}
          <p className="s-muted">
            新版模板增删编辑入口开发中；现阶段可查阅目录。
          </p>
        </>
      )}
      {doc && (
        <Modal wide title="文档切分结果" close={() => setDoc("")}>
          <AtomBrowser documentId={doc} />
        </Modal>
      )}
      {template && (
        <Modal title={template.project_name} close={() => setTemplate(null)}>
          {template.nodes.map((n) => (
            <p
              style={{ paddingLeft: Math.min(n.level - 1, 5) * 16 }}
              key={n.node_id}
            >
              {n.title}
            </p>
          ))}
        </Modal>
      )}
      {upload && (
        <Modal title="批量导入优秀施组" close={() => setUpload(false)}>
          <label>
            任务归档项目
            <select
              value={projectId || projects.data?.[0]?.project_id || ""}
              onChange={(e) => setProjectId(e.target.value)}
            >
              {projects.data?.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <p className="s-muted">
            仅归档后台任务，文档进入独立参考库，不作为项目投标事实。
          </p>
          <label>
            Markdown 文件
            <input
              type="file"
              accept=".md"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
          </label>
          {files.map((f) => (
            <p key={f.name}>{f.name}</p>
          ))}
          <div className="s-dialog-actions">
            <button
              className="primary"
              disabled={busy || !files.length || !projects.data?.length}
              onClick={async () => {
                setBusy(true);
                try {
                  const payload = await Promise.all(
                    files.map(async (f) => ({
                      file_name: f.name,
                      content: await f.text(),
                      project_name: f.name.replace(/\.md$/i, ""),
                      project_type: "待识别",
                      document_kind: "construction_organization",
                      schema_version: "v2",
                      max_batches: null,
                    })),
                  );
                  const task = await A.createGenerationJob(
                    projectId || projects.data![0].project_id,
                    "reference_import_batch",
                    { files: payload },
                  );
                  setJob(task);
                  localStorage.setItem(
                    "studio:import-job",
                    JSON.stringify({
                      project_id: task.project_id,
                      job_id: task.job_id,
                    }),
                  );
                  setUpload(false);
                  toast.success("后台开始处理，成功批次将及时入库");
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              提交 AI 切分
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
