import { useCallback, useState } from "react"
import { Check, CheckCircle2, ChevronRight, FileEdit, FolderKanban, ListTree, PanelsTopLeft, Upload } from "lucide-react"
import type { ProjectResponse } from "@/lib/api"
import { ToastProvider } from "@/components/Toast"
import { cn } from "@/lib/utils"
import { ProjectStep } from "@/steps/ProjectStep"
import { UploadStep } from "@/steps/UploadStep"
import { OutlineStep } from "@/steps/OutlineStep"
import { ChapterStep } from "@/steps/ChapterStep"
import { ExportStep } from "@/steps/ExportStep"

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
  const [active, setActive] = useState<StepId>("project")
  const activeIndex = STEPS.findIndex((s) => s.id === active)

  const goTo = useCallback(
    (id: StepId) => {
      if (id !== "project" && !project) return
      setActive(id)
    },
    [project],
  )

  const selectProject = useCallback((p: ProjectResponse | null) => {
    setProject(p)
    if (p) setActive("upload")
  }, [])

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1480px] items-center justify-between gap-4 px-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-[var(--radius)] bg-primary text-primary-foreground">
              <PanelsTopLeft className="h-5 w-5" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-foreground">施工组织设计生成工作台 1.0</p>
              <p className="text-xs text-muted-foreground">从投标文档到目录、章节版本和最终 Markdown</p>
            </div>
          </div>
          {project ? (
            <div className="hidden items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 sm:flex">
              <span className="h-2 w-2 rounded-full bg-accent" />
              <span className="max-w-[260px] truncate text-xs font-medium text-foreground">{project.name}</span>
            </div>
          ) : null}
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1480px] flex-1 flex-col gap-6 px-5 py-6 lg:flex-row">
        <nav aria-label="生成流程" className="lg:w-64 lg:shrink-0">
          <ol className="flex gap-2 overflow-x-auto lg:flex-col lg:gap-1.5 lg:overflow-visible">
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
                      "group flex w-full items-center gap-3 rounded-[var(--radius)] border px-3 py-2.5 text-left transition-colors",
                      isActive ? "border-primary/30 bg-primary/[0.06]" : "border-transparent hover:border-border hover:bg-card",
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

        <main className="min-w-0 flex-1">
          <div key={active} className="animate-fade-in">
            {active === "project" && <ProjectStep current={project} onSelect={selectProject} />}
            {active === "upload" && project && <UploadStep project={project} onNext={() => setActive("outline")} />}
            {active === "outline" && project && <OutlineStep project={project} onNext={() => setActive("chapter")} />}
            {active === "chapter" && project && <ChapterStep project={project} onNext={() => setActive("export")} />}
            {active === "export" && project && <ExportStep project={project} />}
          </div>
        </main>
      </div>
    </div>
  )
}
