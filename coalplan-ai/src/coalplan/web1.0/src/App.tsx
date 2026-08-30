import { useCallback, useEffect, useState } from "react"
import { AlertTriangle, Check, CheckCircle2, ChevronRight, CircleDot, FileEdit, FolderKanban, ListTree, PanelsTopLeft, Upload } from "lucide-react"
import { getProject, getProjectExperienceSummary, type ProjectExperienceSummary, type ProjectResponse } from "@/lib/api"
import { ToastProvider } from "@/components/Toast"
import { cn } from "@/lib/utils"
import { useAsyncData } from "@/lib/useAsync"
import { ProjectStep } from "@/steps/ProjectStep"
import { UploadStep } from "@/steps/UploadStep"
import { OutlineStep } from "@/steps/OutlineStep"
import { ChapterStep } from "@/steps/ChapterStep"
import { ExportStep } from "@/steps/ExportStep"
import { JobsProvider, TaskCenter } from "@/components/Jobs"

export type StepId = "project" | "upload" | "outline" | "chapter" | "export"

const STEPS: { id: StepId; label: string; hint: string; icon: typeof FolderKanban }[] = [
  { id: "project", label: "项目", hint: "选择模板并创建工程", icon: FolderKanban },
  { id: "upload", label: "资料", hint: "上传投标 Markdown", icon: Upload },
  { id: "outline", label: "目录", hint: "生成、精修和分配字数", icon: ListTree },
  { id: "chapter", label: "章节", hint: "补充材料、生成版本", icon: FileEdit },
  { id: "export", label: "成稿", hint: "合并、审查和导出", icon: CheckCircle2 },
]

export default function App() {
  return (
    <ToastProvider>
      <Studio />
    </ToastProvider>
  )
}

function Studio() {
  const [project, setProject] = useState<ProjectResponse | null>(null)
  const [active, setActive] = useState<StepId>(() => stepFromUrl())
  const [experienceRevision, setExperienceRevision] = useState(0)
  const activeIndex = STEPS.findIndex((s) => s.id === active)
  const refreshExperience = useCallback(() => setExperienceRevision((value) => value + 1), [])

  const goTo = useCallback(
    (id: StepId) => {
      if (id !== "project" && !project) return
      setActive(id)
      updateLocation(project?.project_id ?? null, id)
    },
    [project],
  )

  const selectProject = useCallback((p: ProjectResponse | null) => {
    setProject(p)
    const nextStep: StepId = p ? "upload" : "project"
    setActive(nextStep)
    updateLocation(p?.project_id ?? null, nextStep)
  }, [])

  useEffect(() => {
    const restore = async () => {
      const params = new URLSearchParams(window.location.search)
      const projectId = params.get("project")
      if (!projectId) return
      try {
        setProject(await getProject(projectId))
        setActive(stepFromUrl())
      } catch {
        updateLocation(null, "project", true)
      }
    }
    void restore()
    const onPopState = () => void restore()
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [])

  return (
    <JobsProvider projectId={project?.project_id ?? null}>
    <div className="flex min-h-screen flex-col">
      <header className="glass-surface sticky top-0 z-40 rounded-none border-x-0 border-t-0">
        <div className="mx-auto flex h-16 max-w-[1480px] items-center justify-between gap-4 px-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius)] bg-primary text-primary-foreground shadow-sm">
              <PanelsTopLeft className="h-5 w-5" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-foreground">施工组织设计生成工作台 1.0</p>
              <p className="text-xs text-muted-foreground">从投标文档到目录、章节版本和最终 Markdown</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
          {project ? (
            <div className="hidden max-w-[300px] items-center gap-2 rounded-full border border-white/60 bg-white/55 px-3 py-1.5 shadow-sm backdrop-blur md:flex">
              <span className="h-2 w-2 rounded-full bg-accent" />
              <span className="max-w-[260px] truncate text-xs font-medium text-foreground">{project.name}</span>
            </div>
          ) : null}
          {project ? <TaskCenter /> : null}
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1480px] flex-1 items-start flex-col gap-4 px-4 py-4 sm:px-5 sm:py-6 lg:flex-row lg:gap-6">
        <nav aria-label="生成流程" className="workflow-nav sticky top-16 z-30 -mx-4 w-[calc(100%+2rem)] shrink-0 border-b border-border bg-background/92 px-4 py-2 backdrop-blur-xl sm:-mx-5 sm:w-[calc(100%+2.5rem)] sm:px-5 lg:top-[88px] lg:mx-0 lg:w-64 lg:rounded-[var(--radius)] lg:border lg:border-white/60 lg:bg-white/58 lg:p-2 lg:shadow-[var(--shadow-soft)] lg:backdrop-blur-xl">
          <div className="mb-2 hidden px-2 pt-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground lg:block">工作流</div>
          <ol className="workflow-nav flex gap-2 overflow-x-auto pb-0.5 lg:flex-col lg:gap-1.5 lg:overflow-visible">
            {STEPS.map((step, idx) => {
              const StepIcon = step.icon
              const isActive = step.id === active
              const isDone = idx < activeIndex
              const locked = step.id !== "project" && !project
              return (
                <li key={step.id} className="shrink-0 lg:shrink">
                  <button
                    onClick={() => goTo(step.id)}
                    disabled={locked}
                    className={cn(
                      "group flex min-h-[52px] w-full items-center gap-3 rounded-[var(--radius)] border px-3 py-2.5 text-left transition-[background-color,border-color,box-shadow]",
                      isActive ? "border-primary/30 bg-primary/[0.08] shadow-sm" : "border-transparent hover:border-border hover:bg-white/65 hover:shadow-sm",
                      locked && "cursor-not-allowed opacity-45 hover:border-transparent hover:bg-transparent",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                        isActive
                          ? "border-primary bg-primary text-primary-foreground"
                          : isDone
                            ? "border-accent bg-accent text-accent-foreground"
                            : "border-border bg-card text-muted-foreground",
                      )}
                    >
                      {isDone ? <Check className="h-4 w-4" /> : <StepIcon className="h-4 w-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={cn("block text-sm font-medium", isActive ? "text-primary" : "text-foreground")}>{step.label}</span>
                      <span className="hidden truncate text-xs text-muted-foreground lg:block">{step.hint}</span>
                    </span>
                    {isActive ? <ChevronRight className="hidden h-4 w-4 text-primary lg:block" /> : null}
                  </button>
                </li>
              )
            })}
          </ol>
        </nav>

        <main className="w-full min-w-0 flex-1 pb-10 lg:w-auto">
          {project ? <ProjectPulse key={`${project.project_id}-${active}-${experienceRevision}`} project={project} onNavigate={(step) => goTo(step as StepId)} /> : null}
          <div key={active} className="animate-fade-in">
            {active === "project" && <ProjectStep current={project} onSelect={selectProject} />}
            {active === "upload" && project && (
              <UploadStep
                project={project}
                onNext={() => goTo("outline")}
                onExperienceChanged={refreshExperience}
                onProjectUpdated={setProject}
              />
            )}
            {active === "outline" && project && <OutlineStep project={project} onNext={() => goTo("chapter")} />}
            {active === "chapter" && project && <ChapterStep project={project} onNext={() => goTo("export")} />}
            {active === "export" && project && <ExportStep project={project} />}
          </div>
        </main>
      </div>
    </div>
    </JobsProvider>
  )
}

function ProjectPulse({ project, onNavigate }: { project: ProjectResponse; onNavigate: (step: string) => void }) {
  const summary = useAsyncData<ProjectExperienceSummary>(
    () => getProjectExperienceSummary(project.project_id),
    [project.project_id],
  )
  if (summary.loading) {
    return (
      <section className="glass-surface mb-5 rounded-[var(--radius)] px-4 py-3" aria-label="项目当前进度">
        <p className="text-sm text-muted-foreground">正在读取项目进度...</p>
      </section>
    )
  }
  if (summary.error) {
    return (
      <section className="glass-surface mb-5 rounded-[var(--radius)] px-4 py-3" aria-label="项目当前进度">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">项目进度暂时无法读取，当前页面仍可继续操作。</p>
          <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => void summary.reload()}>
            重新读取
          </button>
        </div>
      </section>
    )
  }
  if (!summary.data) return null
  const data = summary.data
  const progress = data.progress
  const action = data.actions[0]
  const needsAttention = progress.needs_attention_chapters ?? 0
  return (
    <section className="glass-surface mb-5 rounded-[var(--radius)] px-4 py-3" aria-label="项目当前进度">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium text-foreground">
            <CircleDot className="h-4 w-4 text-accent" />
            {data.headline}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>资料 {progress.source_documents ?? 0} 份 / 索引 {progress.indexed_sections ?? 0} 节</span>
            <span>目录 {progress.outline_nodes ?? 0} 节点</span>
            <span>章节 {progress.generated_chapters ?? 0}/{progress.leaf_chapters ?? 0}</span>
            <span>原子 {data.reference_library.published_atoms ?? 0} 条</span>
            {needsAttention ? <span className="inline-flex items-center gap-1 text-[var(--color-warning)]"><AlertTriangle className="h-3 w-3" />待处理 {needsAttention}</span> : null}
          </div>
        </div>
        {action?.target_step ? (
          <button
            type="button"
            className="text-xs font-medium text-primary hover:underline"
            onClick={() => onNavigate(action.target_step!)}
          >
            {action.label}
          </button>
        ) : null}
      </div>
    </section>
  )
}

function stepFromUrl(): StepId {
  const step = new URLSearchParams(window.location.search).get("step") as StepId | null
  return STEPS.some((item) => item.id === step) ? step! : "project"
}

function updateLocation(projectId: string | null, step: StepId, replace = false) {
  const url = new URL(window.location.href)
  if (projectId) url.searchParams.set("project", projectId)
  else url.searchParams.delete("project")
  url.searchParams.set("step", step)
  window.history[replace ? "replaceState" : "pushState"]({}, "", url)
}
