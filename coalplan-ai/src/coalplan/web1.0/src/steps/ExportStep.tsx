import { useState } from "react"
import { Code2, Download, Eye, FileDown, GitMerge, RefreshCw, ShieldCheck } from "lucide-react"
import { generateProject, getFinalMarkdown, mergeProject, runQualityAudit, type ProjectResponse, type QualityAuditResponse, type RunResponse } from "@/lib/api"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, SectionTitle, StatusBadge } from "@/components/ui"
import { Markdown } from "@/components/Markdown"
import { cn, downloadTextFile, safeFileName } from "@/lib/utils"

export function ExportStep({ project }: { project: ProjectResponse }) {
  const toast = useToast()
  const [markdown, setMarkdown] = useState("")
  const [loadingDoc, setLoadingDoc] = useState(false)
  const [merging, setMerging] = useState(false)
  const [generatingAll, setGeneratingAll] = useState(false)
  const [auditing, setAuditing] = useState(false)
  const [audit, setAudit] = useState<QualityAuditResponse | null>(null)
  const [view, setView] = useState<"preview" | "source">("preview")
  const [lastRun, setLastRun] = useState<RunResponse | null>(null)

  const loadFinal = async () => {
    setLoadingDoc(true)
    try {
      const text = await getFinalMarkdown(project.project_id)
      setMarkdown(text)
      toast.success("已载入最终文档")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "尚未生成最终文档，请先合并")
    } finally {
      setLoadingDoc(false)
    }
  }

  const handleGenerateAll = async () => {
    setGeneratingAll(true)
    try {
      const run = await generateProject(project.project_id)
      setLastRun(run)
      if (run.status === "completed") {
        toast.success(`全量生成完成：通过 ${run.passed_count} / ${run.task_count}`)
      } else {
        toast.info(`生成已结束，但仍需人工处理：通过 ${run.passed_count} / ${run.task_count}`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    } finally {
      setGeneratingAll(false)
    }
  }

  const handleMerge = async () => {
    setMerging(true)
    try {
      const run = await mergeProject(project.project_id)
      setLastRun(run)
      if (run.status !== "completed" || !run.final_artifact_path) {
        toast.info(`暂不能形成完整文档：已通过 ${run.passed_count} / ${run.task_count}，请先处理未完成章节`)
        return
      }
      toast.success("合并完成，正在载入文档")
      await loadFinal()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "合并失败")
    } finally {
      setMerging(false)
    }
  }

  const handleAudit = async () => {
    setAuditing(true)
    try {
      const result = await runQualityAudit(project.project_id, true)
      setAudit(result)
      toast.success("质量审查完成")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "审查失败")
    } finally {
      setAuditing(false)
    }
  }

  const handleDownload = () => {
    if (!markdown.trim()) {
      toast.error("请先合并并载入文档")
      return
    }
    downloadTextFile(`${safeFileName(project.name)}.md`, markdown)
    toast.success("已开始下载 Markdown")
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[350px_1fr]">
      <div className="flex flex-col gap-5">
        <Card className="p-5">
          <SectionTitle title="成稿流程" description="生成、合并和质量审查都只给用户可操作结果；是否保留由用户决定。" />
          <div className="mt-4 flex flex-col gap-2.5">
            <ActionRow
              index={1}
              title="全量生成"
              desc="为尚未生成的章节批量生成正文版本"
              icon={<RefreshCw className="h-4 w-4" />}
              action={
                <Button size="sm" variant="outline" onClick={handleGenerateAll} loading={generatingAll}>
                  执行
                </Button>
              }
            />
            <ActionRow
              index={2}
              title="合并文档"
              desc="按目录顺序合并各章选用版本"
              icon={<GitMerge className="h-4 w-4" />}
              action={
                <Button size="sm" onClick={handleMerge} loading={merging}>
                  合并
                </Button>
              }
            />
            <ActionRow
              index={3}
              title="质量审查"
              desc="给出覆盖、结构和再生成建议"
              icon={<ShieldCheck className="h-4 w-4" />}
              action={
                <Button size="sm" variant="accent" onClick={handleAudit} loading={auditing}>
                  审查
                </Button>
              }
            />
          </div>
        </Card>

        <Card className="p-5">
          <SectionTitle title="导出" description="下载标准 Markdown，后续可接 Word/PDF 导出。" />
          <div className="mt-4 flex flex-col gap-2.5">
            <Button variant="outline" onClick={loadFinal} loading={loadingDoc} icon={<Eye className="h-4 w-4" />}>
              载入 / 刷新文档
            </Button>
            <Button onClick={handleDownload} icon={<Download className="h-4 w-4" />} disabled={!markdown.trim()}>
              下载 .md
            </Button>
          </div>
          {markdown.trim() ? <p className="mt-3 text-xs text-muted-foreground">当前文档约 {markdown.length.toLocaleString()} 字符</p> : null}
        </Card>

        {lastRun ? <RunCard run={lastRun} /> : null}

        {audit ? <AuditCard audit={audit} /> : null}
      </div>

      <Card className="flex min-h-[60vh] flex-col p-5">
        <div className="flex items-center justify-between gap-3">
          <SectionTitle title="最终文档" />
          {markdown.trim() ? (
            <div className="flex items-center gap-1 rounded-[var(--radius)] border border-border p-0.5">
              <ViewBtn active={view === "preview"} onClick={() => setView("preview")} icon={<Eye className="h-3.5 w-3.5" />}>
                预览
              </ViewBtn>
              <ViewBtn active={view === "source"} onClick={() => setView("source")} icon={<Code2 className="h-3.5 w-3.5" />}>
                源码
              </ViewBtn>
            </div>
          ) : null}
        </div>
        <div className="mt-4 flex-1">
          {!markdown.trim() ? (
            <EmptyState
              icon={<FileDown className="h-8 w-8" />}
              title="还没有可预览的文档"
              description="完成合并后点击“载入 / 刷新文档”，即可查看并导出。"
              action={
                <Button variant="outline" onClick={loadFinal} loading={loadingDoc} icon={<Eye className="h-4 w-4" />}>
                  载入文档
                </Button>
              }
            />
          ) : view === "preview" ? (
            <div className="h-[64vh] overflow-y-auto rounded-[var(--radius)] border border-border bg-background/40 p-7">
              <Markdown content={markdown} />
            </div>
          ) : (
            <pre className="h-[64vh] overflow-auto rounded-[var(--radius)] border border-border bg-card p-4 font-mono text-[13px] leading-relaxed text-foreground">{markdown}</pre>
          )}
        </div>
      </Card>
    </div>
  )
}

function ActionRow({
  index,
  title,
  desc,
  icon,
  action,
}: {
  index: number
  title: string
  desc: string
  icon: React.ReactNode
  action: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-3 rounded-[var(--radius)] border border-border p-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">
          <span className="mr-1 text-muted-foreground">{index}.</span>
          {title}
        </p>
        <p className="truncate text-xs text-muted-foreground">{desc}</p>
      </div>
      {action}
    </div>
  )
}

function ViewBtn({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button onClick={onClick} className={cn("inline-flex items-center gap-1.5 rounded-[calc(var(--radius)-2px)] px-2.5 py-1 text-xs font-medium transition-colors", active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>
      {icon}
      {children}
    </button>
  )
}

function RunCard({ run }: { run: RunResponse }) {
  return (
    <Card className="p-5">
      <SectionTitle title="最近一次执行" right={<StatusBadge status={run.status} />} />
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <RunMetric label="章节" value={run.task_count} />
        <RunMetric label="通过" value={run.passed_count} />
        <RunMetric label="待处理" value={Math.max(run.task_count - run.passed_count, 0)} />
      </div>
      {run.logs?.length ? (
        <ul className="mt-3 max-h-40 overflow-auto rounded-[var(--radius)] border border-border bg-muted/30 p-3 text-[11px] leading-relaxed text-muted-foreground">
          {run.logs.slice(-8).map((line, index) => (
            <li key={`${index}-${line}`}>{line}</li>
          ))}
        </ul>
      ) : null}
    </Card>
  )
}

function RunMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius)] border border-border bg-muted/30 px-2 py-2">
      <p className="text-base font-semibold text-foreground">{value}</p>
      <p className="text-[11px] text-muted-foreground">{label}</p>
    </div>
  )
}

function AuditCard({ audit }: { audit: QualityAuditResponse }) {
  const report = audit.report ?? {}
  const score = typeof report.score === "number" ? report.score : typeof report.overall_score === "number" ? report.overall_score : null
  return (
    <Card className="p-5">
      <SectionTitle title="审查结果" right={<StatusBadge status={(report.status as string | undefined) ?? audit.revision_targets?.status} />} />
      <div className="mt-4 flex flex-col gap-3">
        {score !== null ? (
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold text-primary">{score}</span>
            <span className="text-xs text-muted-foreground">综合评分</span>
          </div>
        ) : null}
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius)] bg-muted/50 p-3 text-xs text-foreground">{JSON.stringify(report, null, 2)}</pre>
      </div>
    </Card>
  )
}
