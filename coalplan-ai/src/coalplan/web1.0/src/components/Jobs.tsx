import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Loader2, Pause, Play, RefreshCw, RotateCcw, XCircle } from "lucide-react"
import { createGenerationJob, listGenerationJobs, pauseGenerationJob, retryGenerationJob, type GenerationJob, type GenerationJobType } from "@/lib/api"
import { Button } from "@/components/ui"
import { cn, formatDateTime } from "@/lib/utils"
import { useToast } from "@/components/Toast"

type JobsContextValue = {
  jobs: GenerationJob[]
  loading: boolean
  activeJob: GenerationJob | null
  startJob: (type: GenerationJobType, payload?: Record<string, unknown>) => Promise<GenerationJob>
  retryJob: (jobId: string) => Promise<GenerationJob>
  pauseJob: (jobId: string) => Promise<GenerationJob>
  refresh: () => Promise<void>
}

const JobsContext = createContext<JobsContextValue | null>(null)
const terminal = new Set(["completed", "partial", "failed", "interrupted", "paused"])

export function JobsProvider({ projectId, children }: { projectId: string | null; children: React.ReactNode }) {
  const toast = useToast()
  const [jobs, setJobs] = useState<GenerationJob[]>([])
  const [loading, setLoading] = useState(false)
  const announced = useRef(new Map<string, string>())

  const refresh = useCallback(async () => {
    if (!projectId) {
      setJobs([])
      return
    }
    try {
      const next = await listGenerationJobs(projectId)
      setJobs(next)
      next.forEach((job) => {
        const before = announced.current.get(job.job_id)
        announced.current.set(job.job_id, job.status)
        if (before && before !== job.status && terminal.has(job.status)) {
          if (job.status === "completed") toast.success(`${jobLabel(job.job_type)}已完成`)
          else if (job.status === "partial") toast.info(`${jobLabel(job.job_type)}已结束，仍有内容需要处理`)
          else toast.error(`${jobLabel(job.job_type)}未完成，可在任务中心重试`)
          window.dispatchEvent(new CustomEvent("coalplan:job-finished", { detail: job }))
        }
      })
    } catch {
      // Page-level requests already expose backend connectivity. Keep polling quiet here.
    } finally {
      setLoading(false)
    }
  }, [projectId, toast])

  useEffect(() => {
    announced.current.clear()
    setLoading(Boolean(projectId))
    void refresh()
    if (!projectId) return
    const timer = window.setInterval(() => void refresh(), jobs.some((job) => !terminal.has(job.status)) ? 1500 : 5000)
    return () => window.clearInterval(timer)
  }, [projectId, refresh, jobs.some((job) => !terminal.has(job.status))])

  const startJob = useCallback(async (type: GenerationJobType, payload: Record<string, unknown> = {}) => {
    if (!projectId) throw new Error("请先选择项目")
    const job = await createGenerationJob(projectId, type, payload)
    setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)])
    announced.current.set(job.job_id, job.status)
    return job
  }, [projectId])

  const retryJob = useCallback(async (jobId: string) => {
    if (!projectId) throw new Error("请先选择项目")
    const job = await retryGenerationJob(projectId, jobId)
    setJobs((current) => [job, ...current])
    announced.current.set(job.job_id, job.status)
    return job
  }, [projectId])

  const pauseJob = useCallback(async (jobId: string) => {
    if (!projectId) throw new Error("请先选择项目")
    const job = await pauseGenerationJob(projectId, jobId)
    setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)])
    return job
  }, [projectId])

  const value = useMemo(() => ({ jobs, loading, activeJob: jobs.find((job) => !terminal.has(job.status)) ?? null, startJob, retryJob, pauseJob, refresh }), [jobs, loading, startJob, retryJob, pauseJob, refresh])
  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>
}

export function useJobs() {
  const value = useContext(JobsContext)
  if (!value) throw new Error("useJobs must be used inside JobsProvider")
  return value
}

export function TaskCenter() {
  const { jobs, loading, activeJob, pauseJob, retryJob, refresh } = useJobs()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  if (!jobs.length && !loading) return null
  const attention = jobs.filter((job) => ["failed", "interrupted", "partial"].includes(job.status)).length
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex h-9 items-center gap-2 rounded-[var(--radius)] border border-border bg-card px-3 text-xs font-medium text-foreground hover:bg-muted/60"
        aria-expanded={open}
      >
        {activeJob ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : attention ? <AlertTriangle className="h-3.5 w-3.5 text-[var(--color-warning)]" /> : <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-success)]" />}
        {activeJob ? activeJob.message : attention ? `${attention} 项待处理` : "任务中心"}
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {open ? (
        <div className="absolute right-0 top-11 z-50 w-[min(420px,calc(100vw-24px))] rounded-[var(--radius)] border border-border bg-card p-3 shadow-2xl">
          <div className="flex items-center justify-between px-1 pb-2">
            <p className="text-sm font-semibold text-foreground">最近任务</p>
            <Button size="icon" variant="ghost" onClick={() => void refresh()} aria-label="刷新任务"><RefreshCw className="h-4 w-4" /></Button>
          </div>
          <ul className="max-h-[420px] space-y-2 overflow-y-auto">
            {jobs.map((job) => <JobRow key={job.job_id} job={job} onPause={async () => { try { await pauseJob(job.job_id); toast.success("已收到暂止请求，将在当前章节完成后暂停") } catch (err) { toast.error(err instanceof Error ? err.message : "暂止失败") } }} onRetry={async () => { try { await retryJob(job.job_id); toast.success(job.status === "paused" ? "已从保留进度继续生成" : "已重新提交任务") } catch (err) { toast.error(err instanceof Error ? err.message : "重试失败") } }} />)}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function JobRow({ job, onPause, onRetry }: { job: GenerationJob; onPause: () => Promise<void>; onRetry: () => Promise<void> }) {
  const running = !terminal.has(job.status)
  const Icon = running ? Loader2 : job.status === "completed" ? CheckCircle2 : job.status === "partial" ? AlertTriangle : XCircle
  const progress = job.total > 0 ? Math.min(100, Math.round(job.current / job.total * 100)) : null
  return (
    <li className="rounded-[var(--radius)] border border-border p-3">
      <div className="flex items-start gap-2.5">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", running && "animate-spin text-primary", job.status === "completed" && "text-[var(--color-success)]", ["partial", "interrupted"].includes(job.status) && "text-[var(--color-warning)]", job.status === "failed" && "text-[var(--color-danger)]")} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-xs font-semibold text-foreground">{jobLabel(job.job_type)}</p>
            <span className="shrink-0 text-[10px] text-muted-foreground">{formatDateTime(job.updated_at)}</span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{job.message}</p>
          {running && progress !== null ? <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-[width]" style={{ width: `${progress}%` }} /></div> : null}
          {job.error ? <details className="mt-2 text-[11px] text-[var(--color-danger)]"><summary className="cursor-pointer">查看失败详情</summary><p className="mt-1 break-words">{job.error}</p></details> : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {job.job_type === "project_generation" && running ? <Button size="icon" variant="ghost" onClick={() => void onPause()} aria-label="暂止全量生成" title="暂止全量生成"><Pause className="h-4 w-4" /></Button> : null}
          {["failed", "interrupted", "partial", "paused"].includes(job.status) ? <Button size="icon" variant="ghost" onClick={() => void onRetry()} aria-label={job.status === "paused" ? "继续生成" : "重试任务"} title={job.status === "paused" ? "继续生成" : "重试任务"}>{job.status === "paused" ? <Play className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}</Button> : null}
        </div>
      </div>
    </li>
  )
}

export function jobLabel(type: GenerationJobType) {
  return ({ directory_generation: "目录生成", chapter_generation: "章节生成", child_chapter_generation: "子章节生成", project_generation: "全量生成", chapter_group_recommendation: "联合生成建议", chapter_batch_generation: "批量章节更新", supplement_batch_ai_fill: "AI补全建议", quality_audit: "质量审查", compliance_review: "规范审查", outline_proposal: "目录调整建议", outline_refine: "目录精修建议", chapter_plan_proposal: "章节提纲优化", chapter_edit_proposal: "正文修改建议", reference_import: "优秀施组切分", reference_import_batch: "批量切分优秀施组" } as const)[type]
}
