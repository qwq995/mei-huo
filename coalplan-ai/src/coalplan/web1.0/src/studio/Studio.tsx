import { useCallback, useEffect, useState, useRef } from "react";
import {
  BookOpen,
  Library,
  FolderOpen,
  Files,
  ListTree,
  FilePenLine,
  PackageCheck,
  PanelLeftClose,
  PanelLeftOpen,
  ArrowUpRight,
  Layers3,
} from "lucide-react";
import * as A from "@/lib/api";
import { JobsProvider, TaskCenter } from "@/components/Jobs";
import { useToast } from "@/components/Toast";
import { Projects, Sources, Delivery } from "./WorkspacePages";
import { Outline } from "./Outline";
import { Writer } from "./Writer";
import { Knowledge } from "./Knowledge";
import { Rules } from "./Rules";
import { Status } from "./common";

const writing = [
  { id: "projects", label: "项目总览", icon: FolderOpen },
  { id: "sources", label: "项目资料", icon: Files },
  { id: "outline", label: "目录规划", icon: ListTree },
  { id: "writer", label: "章节编写", icon: FilePenLine },
  { id: "delivery", label: "审查与交付", icon: PackageCheck },
];
const management = [
  { id: "atoms", label: "原子要素", icon: Layers3 },
  { id: "documents", label: "参考文档", icon: Files },
  { id: "templates", label: "目录模板", icon: ListTree },
  { id: "skills", label: "写作技巧", icon: BookOpen },
  { id: "standards", label: "规范条例", icon: PackageCheck },
];
function locationState() {
  const p = new URLSearchParams(location.search);
  return { view: p.get("view") || "projects", project: p.get("project") || "" };
}
export function Studio() {
  const [route, setRoute] = useState(locationState),
    [project, setProject] = useState<A.ProjectResponse | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [collapsed, setCollapsed] = useState(false),
    [dirty, setDirty] = useState(false);
  const toast = useToast();
  const requestId = useRef(0);
  const admin = management.some((x) => x.id === route.view);
  const restore = useCallback(async (id: string) => {
    const token = ++requestId.current;
    setError("");
    setLoading(Boolean(id));
    try {
      const next = id ? await A.getProject(id) : null;
      if (token === requestId.current) setProject(next);
    } catch (e) {
      if (token === requestId.current) setError((e as Error).message);
    } finally {
      if (token === requestId.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void restore(route.project);
  }, [route.project, restore]);
  useEffect(() => {
    const back = () => {
      if (
        dirty &&
        !confirm("仍有未提交的正文，请确认修改已经保存。是否离开？")
      ) {
        history.pushState(
          {},
          "",
          `studio.html?view=${route.view}&project=${route.project}`,
        );
        return;
      }
      setDirty(false);
      setRoute(locationState());
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, [dirty, route]);
  const navigate = (view: string, id = route.project) => {
    if (dirty && !confirm("正文尚未提交，请确认修改已经保存。是否离开？"))
      return;
    setDirty(false);
    const next = { view, project: id };
    history.pushState(
      {},
      "",
      `studio.html?view=${view}${id ? `&project=${encodeURIComponent(id)}` : ""}`,
    );
    setRoute(next);
  };
  const label =
    [...writing, ...management].find((x) => x.id === route.view)?.label ||
    "项目总览";
  return (
    <JobsProvider projectId={route.project || null}>
      <div className={`s-shell ${collapsed ? "compact" : ""}`}>
        <aside className="s-sidebar">
          <a className="s-brand" href="studio.html">
            <span className="s-brand-mark">
              <Layers3 size={22} />
            </span>
            <span>
              筑序<small>施工组织设计</small>
            </span>
          </a>
          <div className="s-space">
            <button aria-pressed={!admin} onClick={() => navigate("projects")}>
              <BookOpen size={17} />
              <span>文档编写</span>
            </button>
            <button aria-pressed={admin} onClick={() => navigate("atoms")}>
              <Library size={17} />
              <span>知识管理</span>
            </button>
          </div>
          <p className="s-nav-label">{admin ? "知识资产" : "项目工作区"}</p>
          <nav aria-label={admin ? "知识管理导航" : "编写导航"}>
            {(admin ? management : writing).map((x) => (
              <button
                key={x.id}
                aria-current={route.view === x.id ? "page" : undefined}
                title={x.label}
                onClick={() => navigate(x.id)}
              >
                <x.icon size={18} />
                <span>{x.label}</span>
              </button>
            ))}
          </nav>
          <div className="s-sidebar-bottom">
            <a href={`/?project=${route.project}&step=project`}>
              <ArrowUpRight size={16} />
              <span>打开旧版</span>
            </a>
            <button
              title={collapsed ? "展开导航" : "收起导航"}
              onClick={() => setCollapsed(!collapsed)}
            >
              {collapsed ? (
                <PanelLeftOpen size={18} />
              ) : (
                <PanelLeftClose size={18} />
              )}
              <span>收起导航</span>
            </button>
          </div>
        </aside>
        <div className="s-main">
          <header className="s-topbar">
            <div className="s-breadcrumb">
              {admin ? "知识管理" : "文档编写"}
              <span>/</span>
              <strong>{label}</strong>
            </div>
            <div className="s-top-actions">
              <span className="s-project-name" title={project?.name}>
                {project?.name || "未选择项目"}
              </span>
              <TaskCenter />
            </div>
          </header>
          <main className="s-content">
            <div className="s-page-heading">
              <div>
                <p>{admin ? "知识资产中心" : "工程文档工作台"}</p>
                <h1>{label}</h1>
              </div>
              {!admin && route.view !== "projects" && (
                <button onClick={() => navigate("projects")}>切换项目</button>
              )}
            </div>
            <Status
              loading={loading}
              error={error}
              retry={() => void restore(route.project)}
            />
            {admin ? (
              route.view === "skills" || route.view === "standards" ? (
                <Rules kind={route.view} />
              ) : (
                <Knowledge view={route.view} />
              )
            ) : route.view === "projects" ? (
              <Projects
                select={(p) => {
                  setProject(p);
                  navigate("sources", p.project_id);
                }}
              />
            ) : !project ? (
              <div className="s-empty">
                <FolderOpen size={36} />
                <h2>先选择一个项目</h2>
                <button
                  className="primary"
                  onClick={() => navigate("projects")}
                >
                  选择项目
                </button>
              </div>
            ) : (
              <div key={`${route.project}:${route.view}`}>
                {route.view === "sources" && (
                  <Sources project={project} next={() => navigate("outline")} />
                )}
                {route.view === "outline" && (
                  <Outline project={project} next={() => navigate("writer")} />
                )}
                {route.view === "writer" && (
                  <Writer project={project} onDirty={setDirty} />
                )}
                {route.view === "delivery" && <Delivery project={project} />}
              </div>
            )}
            {admin && (
              <p className="s-footnote">
                工作空间分离不等同于访问权限隔离。当前为本地工作台。
              </p>
            )}
          </main>
          <footer className="s-bottom">
            {admin
              ? "知识版本独立维护 · 项目选择不会自动覆盖"
              : "投标事实 · 已发布原子 · 写作技巧 · 规范审查"}
            <button
              onClick={() => {
                navigator.clipboard
                  .writeText(location.href)
                  .then(() => toast.success("已复制工作位置"));
              }}
            >
              复制工作位置
            </button>
          </footer>
        </div>
      </div>
    </JobsProvider>
  );
}
