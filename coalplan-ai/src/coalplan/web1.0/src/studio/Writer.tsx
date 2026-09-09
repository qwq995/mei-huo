import { useEffect, useState } from "react";
import MdEditor from "react-markdown-editor-lite";
import "react-markdown-editor-lite/lib/index.css";
import {
  Save,
  WandSparkles,
  History,
  BookOpen,
  ChevronRight,
} from "lucide-react";
import * as A from "@/lib/api";
import { useJobs } from "@/components/Jobs";
import { useToast } from "@/components/Toast";
import { AtomBrowser } from "./Knowledge";
import {
  Document,
  Modal,
  Filter,
  Status,
  useResource,
  markdown,
} from "./common";

export function Writer({
  project,
  onDirty,
}: {
  project: A.ProjectResponse;
  onDirty: (v: boolean) => void;
}) {
  const nodes = useResource(
      () => A.listOutlineNodes(project.project_id),
      [project.project_id],
    ),
    [id, setId] = useState(
      () =>
        localStorage.getItem(`studio:last-chapter:${project.project_id}`) || "",
    ),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [body, setBody] = useState(""),
    [baseline, setBaseline] = useState(""),
    [candidate, setCandidate] = useState<A.ChapterVersion | null>(null),
    [history, setHistory] = useState(false),
    [basis, setBasis] = useState(false),
    [prefs, setPrefs] = useState<A.ChapterBasisPreferences | null>(null),
    [plan, setPlan] = useState<
      (A.ChapterGenerationPlan & { writing_skills?: string[] }) | null
    >(null),
    [skill, setSkill] = useState<Record<string, unknown> | null>(null),
    [busy, setBusy] = useState(false),
    [mode, setMode] = useState("split");
  const [batch, setBatch] = useState(false),
    [parallel, setParallel] = useState(2);
  const [draftError, setDraftError] = useState("");
  const workspace = useResource(
      () =>
        id ? A.getWorkspace(project.project_id, id) : Promise.resolve(null),
      [project.project_id, id],
    ),
    toast = useToast(),
    { activeJob, startJob } = useJobs();
  const current = workspace.data?.versions.find(
      (v) => v.id === workspace.data?.selected_version_id,
    ),
    dirty = body !== baseline;
  const draftKey = `studio:draft:${project.project_id}:${id}`;
  useEffect(() => {
    if (nodes.data?.length && !nodes.data.some((n) => n.node_id === id))
      setId(
        nodes.data.find(
          (n) =>
            n.enabled !== false &&
            !n.selected_version_id &&
            !nodes.data?.some(
              (child) =>
                child.parent_id === n.node_id && child.enabled !== false,
            ),
        )?.node_id || nodes.data[0].node_id,
      );
  }, [nodes.data, id]);
  useEffect(() => {
    if (id && nodes.data?.some((n) => n.node_id === id))
      localStorage.setItem(`studio:last-chapter:${project.project_id}`, id);
  }, [id, nodes.data, project.project_id]);
  useEffect(() => {
    if (!workspace.data || workspace.data.outline_node.node_id !== id) return;
    const saved =
      workspace.data.versions.find(
        (v) => v.id === workspace.data?.selected_version_id,
      )?.markdown || "";
    setBaseline(saved);
    setBody(localStorage.getItem(draftKey) ?? saved);
  }, [workspace.data, draftKey]);
  useEffect(() => {
    onDirty(dirty);
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty, onDirty]);
  useEffect(() => {
    if (id && dirty && workspace.data?.outline_node.node_id === id) {
      try {
        localStorage.setItem(draftKey, body);
        setDraftError("");
      } catch {
        setDraftError(
          "浏览器存储空间不足，请立即保存版本；关闭页面可能丢失未提交修改。",
        );
      }
    }
  }, [body, id, dirty, draftKey, workspace.data]);
  useEffect(() => {
    const done = (e: Event) => {
      if ((e as CustomEvent).detail.project_id === project.project_id) {
        if (!dirty) workspace.reload();
        nodes.reload();
      }
    };
    window.addEventListener("coalplan:job-finished", done);
    return () => window.removeEventListener("coalplan:job-finished", done);
  }, [dirty, id, project.project_id]);
  const run = async (f: () => Promise<void>) => {
    setBusy(true);
    try {
      await f();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const choose = (nid: string) => {
    if (dirty && !confirm(draftError || "正文尚未提交，是否切换章节？")) return;
    setBody("");
    setBaseline("");
    setId(nid);
    localStorage.setItem(`studio:last-chapter:${project.project_id}`, nid);
    setSkill(null);
  };
  const node = nodes.data?.find((n) => n.node_id === id);
  return (
    <>
      {draftError && (
        <p className="s-alert" role="alert">
          {draftError}
        </p>
      )}
      <div className="s-toolbar">
        <span className="s-subtitle">
          {activeJob ? activeJob.message : "正文编辑与版本选用"}
        </span>
        <button
          disabled={Boolean(activeJob) || busy || dirty}
          onClick={() => setBatch(true)}
        >
          批量生成待完成章节
        </button>
      </div>
      <div className="s-writing-layout">
        <aside className="s-chapter-nav">
          <Filter value={query} change={setQuery} placeholder="搜索章节" />
          <select
            aria-label="章节状态"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">全部章节</option>
            <option value="pending">待生成</option>
            <option value="done">已有正文</option>
          </select>
          <Status {...nodes} retry={nodes.reload} />
          <div className="s-chapter-scroll">
            {nodes.data
              ?.filter(
                (n) =>
                  n.enabled !== false &&
                  n.title.includes(query) &&
                  (filter === "all" ||
                    (filter === "done"
                      ? Boolean(n.selected_version_id)
                      : !n.selected_version_id)),
              )
              .map((n) => (
                <button
                  key={n.node_id}
                  aria-current={id === n.node_id ? "page" : undefined}
                  onClick={() => choose(n.node_id)}
                >
                  <span
                    className={`s-node-dot ${n.selected_version_id ? "" : "pending"}`}
                  />
                  <span>{n.title}</span>
                  <ChevronRight size={13} />
                </button>
              ))}
          </div>
        </aside>
        <section className="s-writing-main">
          <div className="s-writing-heading">
            <div>
              <span className="s-muted">
                {current ? `选用版本 V${current.version_no}` : "尚无选用版本"}
                {dirty ? " · 本地草稿未提交" : ""}
              </span>
              <h2>{node?.title || "选择章节"}</h2>
            </div>
            <button
              className="primary"
              disabled={Boolean(activeJob) || busy || !id || dirty}
              onClick={() =>
                void run(async () => {
                  await startJob("chapter_generation", { node_id: id });
                })
              }
            >
              <WandSparkles size={16} />
              {current ? "重新生成" : "生成本章"}
            </button>
          </div>
          <div className="s-editor-toolbar">
            <div className="s-actions">
              <button
                disabled={!id || busy}
                onClick={() =>
                  void run(async () => {
                    const [p, t] = await Promise.all([
                      A.getChapterBasisPreferences(project.project_id, id),
                      A.getChapterGenerationPlan(project.project_id, id),
                    ]);
                    setPrefs(p);
                    setPlan(t);
                    setBasis(true);
                  })
                }
              >
                <BookOpen size={16} />
                依据与写作任务
              </button>
              <button
                disabled={!workspace.data}
                onClick={() => setHistory(true)}
              >
                <History size={16} />
                版本
              </button>
            </div>
            <div className="s-actions">
              <select
                aria-label="正文显示模式"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="split">左右对照</option>
                <option value="edit">仅编辑</option>
                <option value="preview">仅预览</option>
              </select>
              <button
                className="primary"
                disabled={!id || busy || !dirty}
                onClick={() =>
                  void run(async () => {
                    setCandidate(
                      await A.createManualVersion(
                        project.project_id,
                        id,
                        node?.title || "章节",
                        body,
                        false,
                      ),
                    );
                  })
                }
              >
                <Save size={16} />
                保存版本
              </button>
            </div>
          </div>
          <Status {...workspace} retry={workspace.reload} />
          {dirty && (
            <div className="s-draft-bar">
              未保存的修改已保存在此浏览器
              <button
                onClick={() => {
                  if (confirm("放弃本地修改并恢复选用版本？")) {
                    localStorage.removeItem(draftKey);
                    setBody(baseline);
                  }
                }}
              >
                放弃修改
              </button>
            </div>
          )}
          {id && !workspace.loading && (
            <MdEditor
              key={`${id}:${mode}`}
              value={body}
              style={{ height: "min(68vh,850px)", minHeight: 360 }}
              view={{
                menu: true,
                md: mode !== "preview",
                html: mode !== "edit",
              }}
              renderHTML={(text) => markdown.render(text)}
              onChange={({ text }) => setBody(text)}
              config={{
                canView: {
                  menu: true,
                  md: true,
                  html: true,
                  fullScreen: true,
                  hideMenu: true,
                },
                syncScrollMode: ["leftFollowRight", "rightFollowLeft"],
              }}
            />
          )}
        </section>
      </div>
      {batch && (
        <Modal title="确认批量生成范围" close={() => setBatch(false)}>
          <p>只处理没有选用版本的章节，保留已有正文及用户固定的依据。</p>
          <label>
            章节并行数量
            <select
              value={parallel}
              onChange={(e) => setParallel(Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n} 个章节
                </option>
              ))}
            </select>
          </label>
          <div className="s-batch-list">
            {nodes.data
              ?.filter((n) => n.enabled !== false && !n.selected_version_id)
              .map((n) => (
                <p key={n.node_id}>{n.title}</p>
              ))}
          </div>
          <div className="s-dialog-actions">
            <button onClick={() => setBatch(false)}>取消</button>
            <button
              className="primary"
              disabled={busy || Boolean(activeJob)}
              onClick={() =>
                void run(async () => {
                  await startJob("project_generation", {
                    only_pending: true,
                    max_parallel_chapters: parallel,
                  });
                  setBatch(false);
                })
              }
            >
              确认开始生成
            </button>
          </div>
        </Modal>
      )}
      {history && (
        <Modal title="选择版本进行比对" close={() => setHistory(false)}>
          {workspace.data?.versions.length ? (
            workspace.data.versions.map((v) => (
              <button
                className="s-list-row"
                key={v.id}
                onClick={() => {
                  setCandidate(v);
                  setHistory(false);
                }}
              >
                <span>
                  V{v.version_no} ·{" "}
                  {v.source_type === "user" ? "人工编辑" : "生成版本"}
                  <small>{new Date(v.created_at).toLocaleString()}</small>
                </span>
                <span>{v.id === current?.id ? "当前选用" : "比对并选用"}</span>
              </button>
            ))
          ) : (
            <p>尚无历史版本。</p>
          )}
        </Modal>
      )}
      {candidate && (
        <Modal wide title="比对后选用正文版本" close={() => setCandidate(null)}>
          <div className="s-compare">
            <section>
              <h3>当前选用 {current ? `V${current.version_no}` : "无"}</h3>
              <Document text={current?.markdown || "暂无正文"} />
            </section>
            <section>
              <h3>候选 V{candidate.version_no}</h3>
              <Document text={candidate.markdown} />
            </section>
          </div>
          <div className="s-dialog-actions">
            <button
              onClick={() => {
                setCandidate(null);
                workspace.reload();
              }}
            >
              保留当前版本
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await A.selectVersion(project.project_id, id, candidate.id);
                  localStorage.removeItem(draftKey);
                  setBody(candidate.markdown);
                  setBaseline(candidate.markdown);
                  setCandidate(null);
                  workspace.reload();
                  nodes.reload();
                  toast.success("已选用新版本");
                })
              }
            >
              确认选用候选版本
            </button>
          </div>
        </Modal>
      )}
      {basis && prefs && plan && (
        <Modal
          wide
          title="本章依据与写作任务"
          close={() => {
            if (confirm("尚未保存的依据调整将放弃，是否关闭？"))
              setBasis(false);
          }}
        >
          <div className="s-form-grid">
            <label>
              写作任务：本章必须写什么
              <textarea
                rows={6}
                value={plan.items
                  .filter((x) => x.enabled)
                  .map((x) => x.title)
                  .join("\n")}
                onChange={(e) =>
                  setPlan({
                    ...plan,
                    items: e.target.value.split("\n").map((title, i) => ({
                      ...plan.items[i],
                      item_id: plan.items[i]?.item_id || `task_${i}`,
                      title,
                      purpose: plan.items[i]?.purpose || "",
                      key_points: [title],
                      evidence_requirement:
                        plan.items[i]?.evidence_requirement || "",
                      output_form: "段落",
                      enabled: true,
                      sort_order: i,
                    })),
                  })
                }
              />
            </label>
            <label>
              附加写作要求
              <textarea
                rows={6}
                value={prefs.prompt}
                onChange={(e) => setPrefs({ ...prefs, prompt: e.target.value })}
              />
            </label>
          </div>
          <details className="s-band">
            <summary>写作技巧：如何组织与表达</summary>
            <label>
              本章写作技巧
              <textarea
                rows={5}
                value={plan.writing_skills?.join("\n") || ""}
                onChange={(e) =>
                  setPlan({
                    ...plan,
                    writing_skills: e.target.value.split("\n"),
                  })
                }
              />
            </label>
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const preview = await A.getChapterGenerationPreflight(
                    project.project_id,
                    id,
                  );
                  setSkill(preview.chapter_writing_skill || null);
                  if (!preview.chapter_writing_skill)
                    toast.info("本章暂无 AI 技巧，可直接编辑上述写作技巧。");
                })
              }
            >
              查看已匹配 AI 技巧
            </button>
            {skill && (
              <div className="s-form-grid">
                {(
                  [
                    ["mission", "章节表达目标"],
                    ["organization_logic", "组织顺序"],
                    ["detail_strategy", "展开方法"],
                    ["fact_boundary_rules", "事实边界"],
                    ["prompt_instructions", "写作指令"],
                    ["avoid", "避免事项"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <textarea
                      rows={4}
                      value={
                        Array.isArray(skill[key])
                          ? (skill[key] as string[]).join("\n")
                          : String(skill[key] || "")
                      }
                      onChange={(e) =>
                        setSkill({
                          ...skill,
                          [key]:
                            key === "mission"
                              ? e.target.value
                              : e.target.value.split("\n"),
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            )}
          </details>
          <h3>已发布原子 · 已固定 {prefs.atom_ids.length} 条</h3>
          <AtomBrowser
            published
            selected={prefs.atom_ids}
            onSelect={(ids) =>
              setPrefs({
                ...prefs,
                atom_ids: ids,
                excluded_atom_ids: [
                  ...new Set([
                    ...prefs.excluded_atom_ids,
                    ...prefs.atom_ids.filter((old) => !ids.includes(old)),
                  ]),
                ].filter((old) => !ids.includes(old)),
              })
            }
          />
          <div className="s-dialog-actions">
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  if (skill)
                    await A.saveChapterWritingSkill(
                      project.project_id,
                      id,
                      skill,
                    );
                  await A.saveChapterGenerationPlan(project.project_id, id, {
                    ...plan,
                    ...(skill
                      ? {
                          writing_skills: [
                            ...(plan.writing_skills || []),
                            ...[
                              "organization_logic",
                              "detail_strategy",
                              "fact_boundary_rules",
                              "prompt_instructions",
                            ].flatMap((key) =>
                              Array.isArray(skill[key])
                                ? (skill[key] as string[])
                                : [],
                            ),
                          ],
                        }
                      : {}),
                    status: "confirmed",
                    source: "user",
                  });
                  await A.saveChapterBasisPreferences(
                    project.project_id,
                    id,
                    prefs,
                  );
                  setBasis(false);
                  toast.success("本章任务与原子选择已保存");
                })
              }
            >
              保存本章依据
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
