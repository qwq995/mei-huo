import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, Code2, Download, Eye, FileDown, GitMerge, Pause, RefreshCw, ShieldCheck } from "lucide-react"
import { applySupplementBatch, createSupplementBatch, getCurrentGeneratedMarkdown, getFinalMarkdown, listChapterTasks, mergeProject, type ProjectResponse, type QualityAuditResponse, type RunResponse, type SupplementBatch } from "@/lib/api"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, SectionTitle, StatusBadge } from "@/components/ui"
import { Markdown } from "@/components/Markdown"
import { cn, downloadTextFile, safeFileName } from "@/lib/utils"
import { useJobs } from "@/components/Jobs"
import { useAsyncData } from "@/lib/useAsync"

export function ExportStep({ project }: { project: ProjectResponse }) {
  const toast = useToast()
  const { startJob, activeJob, pauseJob } = useJobs()
  const tasks = useAsyncData(() => listChapterTasks(project.project_id), [project.project_id])
  const [markdown, setMarkdown] = useState("")
  const [loadingDoc, setLoadingDoc] = useState(false)
  const [merging, setMerging] = useState(false)
  const [generatingAll, setGeneratingAll] = useState(false)
  const [auditing, setAuditing] = useState(false)
  const [audit, setAudit] = useState<QualityAuditResponse | null>(null)
  const [view, setView] = useState<"preview" | "source">("preview")
  const [lastRun, setLastRun] = useState<RunResponse | null>(null)
  const [loadedAt, setLoadedAt] = useState<string | null>(null)
  const [documentKind, setDocumentKind] = useState<"final" | "current">("final")
  const [groupRecommendation, setGroupRecommendation] = useState<Record<string, unknown> | null>(null)
  const [groupLoading, setGroupLoading] = useState(false)
  const [batch, setBatch] = useState<SupplementBatch | null>(null)
  const [batchValues, setBatchValues] = useState<Record<string, string>>({})
  const [batchLoading, setBatchLoading] = useState(false)
  const [parallelChapterCount, setParallelChapterCount] = useState(2)
  const remaining = useMemo(() => (tasks.data ?? []).filter((task) => task.status !== "passed").length, [tasks.data])

  const loadFinal = async () => {
    setLoadingDoc(true)
    try {
      const text = await getFinalMarkdown(project.project_id)
      setMarkdown(text)
      setDocumentKind("final")
      setLoadedAt(new Date().toISOString())
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
      await startJob("project_generation", { only_pending: true, max_parallel_chapters: parallelChapterCount })
      toast.success(`全量生成已开始，将同时处理 ${parallelChapterCount} 个章节`)
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
      await startJob("quality_audit", { apply_feedback: true })
      toast.success("质量审查已开始，完成后会自动显示结果")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "审查失败")
    } finally {
      setAuditing(false)
    }
  }

  const handlePauseAll = async () => {
    if (!activeJob || activeJob.job_type !== "project_generation") return
    try {
      await pauseJob(activeJob.job_id)
      toast.success("已收到暂止请求，将在当前章节完成后暂停")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "暂止失败")
    }
  }

  const loadCurrent = async () => {
    setLoadingDoc(true)
    try {
      const text = await getCurrentGeneratedMarkdown(project.project_id)
      setMarkdown(text)
      setDocumentKind("current")
      setLoadedAt(new Date().toISOString())
      toast.success("已载入当前已生成内容")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "暂时没有可导出的已生成内容")
    } finally {
      setLoadingDoc(false)
    }
  }

  const handleRecommendGroups = async () => {
    setGroupLoading(true)
    try {
      await startJob("chapter_group_recommendation")
      toast.success("正在分析可一起生成的章节")
    } catch (err) { toast.error(err instanceof Error ? err.message : "推荐失败") }
    finally { setGroupLoading(false) }
  }

  const handleBuildBatch = async () => {
    setBatchLoading(true)
    try {
      const result = await createSupplementBatch(project.project_id)
      setBatch(result)
      setBatchValues(Object.fromEntries(result.items.map((item) => [item.item_id, item.value || ""])))
    } catch (err) { toast.error(err instanceof Error ? err.message : "整理待补信息失败") }
    finally { setBatchLoading(false) }
  }

  const handleAISuggest = async () => {
    if (!batch) return
    try { await startJob("supplement_batch_ai_fill", { batch_id: batch.batch_id }); toast.success("正在生成待补信息建议，请稍后审核") }
    catch (err) { toast.error(err instanceof Error ? err.message : "AI建议失败") }
  }

  const handleGenerateGroup = async (group: Record<string, unknown>) => {
    const nodeIds = Array.isArray(group.node_ids) ? group.node_ids.map(String).filter(Boolean) : []
    if (!nodeIds.length) return
    if (!window.confirm(`将按独立章节生成 ${nodeIds.length} 个节点，是否继续？`)) return
    try { await startJob("chapter_batch_generation", { node_ids: nodeIds, max_parallel_chapters: parallelChapterCount }); toast.success(`联合生成任务已提交，将同时处理 ${parallelChapterCount} 个章节`) }
    catch (err) { toast.error(err instanceof Error ? err.message : "提交联合生成失败") }
  }

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id !== project.project_id) return
      if (job.job_type === "project_generation") {
        setLastRun(job.result as RunResponse)
        void tasks.reload()
      }
      if (job.job_type === "quality_audit" && job.status === "completed") setAudit(job.result as QualityAuditResponse)
      if (job.job_type === "chapter_group_recommendation" && job.status === "completed") setGroupRecommendation(job.result as Record<string, unknown>)
      if (job.job_type === "supplement_batch_ai_fill" && job.status === "completed" && job.result && typeof job.result === "object") {
        const next = (job.result as { batch?: SupplementBatch }).batch
        if (next) setBatch(next)
      }
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [project.project_id, tasks.reload])

  const handleDownload = () => {
    if (!markdown.trim()) {
      toast.error("请先合并并载入文档")
      return
    }
    downloadTextFile(`${safeFileName(project.name)}${documentKind === "current" ? "-阶段性合稿" : ""}.md`, markdown)
    toast.success("已开始下载 Markdown")
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[350px_1fr]">
      <div className="flex flex-col gap-5">
        <Card className="p-5">
          <SectionTitle title="下一步" description={remaining ? `还有 ${remaining} 个章节未通过，建议先继续生成。` : "章节已准备完成，可以合并最新选用版本。"} />
          <div className="mt-4 flex gap-2">
            <Button className="min-w-0 flex-1" onClick={remaining ? handleGenerateAll : handleMerge} loading={remaining ? generatingAll || activeJob?.job_type === "project_generation" : merging} icon={remaining ? <RefreshCw className="h-4 w-4" /> : <GitMerge className="h-4 w-4" />}>
              {remaining ? `继续生成 ${remaining} 个章节` : "合并最新版本"}
            </Button>
            {remaining && activeJob?.job_type === "project_generation" ? <Button variant="outline" onClick={handlePauseAll} icon={<Pause className="h-4 w-4" />} title="当前章节完成后暂止全量生成">暂止</Button> : null}
          </div>
          <label className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>并行章节数</span>
            <select
              aria-label="并行章节数"
              className="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground"
              value={parallelChapterCount}
              onChange={(event) => setParallelChapterCount(Math.max(1, Math.min(8, Number(event.target.value) || 1)))}
            >
              {[1, 2, 3, 4, 5, 6, 7, 8].map((value) => <option key={value} value={value}>{value} 个</option>)}
            </select>
          </label>
          <div className="mt-4 flex flex-col gap-2.5">
            <ActionRow
              index={1}
              title="推荐联合生成"
              desc="分析无强依赖、可共享依据的章节组合"
              icon={<RefreshCw className="h-4 w-4" />}
              action={<Button size="sm" variant="outline" onClick={handleRecommendGroups} loading={groupLoading || activeJob?.job_type === "chapter_group_recommendation"}>分析</Button>}
            />
            <ActionRow
              index={2}
              title="汇总待补信息"
              desc="跨章节去重，形成一份可回填的项目表单"
              icon={<FileDown className="h-4 w-4" />}
              action={<Button size="sm" variant="outline" onClick={handleBuildBatch} loading={batchLoading}>整理</Button>}
            />
            <ActionRow
              index={3}
              title="质量审查"
              desc="给出覆盖、结构和再生成建议"
              icon={<ShieldCheck className="h-4 w-4" />}
              action={
                <Button size="sm" variant="accent" onClick={handleAudit} loading={auditing || activeJob?.job_type === "quality_audit"}>
                  审查
                </Button>
              }
            />
          </div>
        </Card>

        <Card className="p-5">
          <SectionTitle title="导出" description="正式合并稿和当前已生成内容均可下载为 Markdown。" />
          <div className="mt-4 flex flex-col gap-2.5">
            <Button variant="outline" onClick={loadCurrent} loading={loadingDoc} icon={<FileDown className="h-4 w-4" />}>
              载入当前已生成内容
            </Button>
            <Button variant="outline" onClick={loadFinal} loading={loadingDoc} icon={<Eye className="h-4 w-4" />}>
              载入正式合并稿
            </Button>
            <Button onClick={handleDownload} icon={<Download className="h-4 w-4" />} disabled={!markdown.trim()}>
              下载 .md
            </Button>
          </div>
          {markdown.trim() ? <p className="mt-3 text-xs text-muted-foreground">{documentKind === "current" ? "当前已生成内容" : "正式合并稿"} · 约 {markdown.length.toLocaleString()} 字符 · 载入于 {loadedAt ? new Date(loadedAt).toLocaleString("zh-CN") : "本次会话"}</p> : null}
        </Card>

        {lastRun ? <RunCard run={lastRun} /> : null}

        {audit ? <AuditCard audit={audit} /> : null}
        {groupRecommendation ? <GroupRecommendationCard recommendation={groupRecommendation} onGenerateGroup={handleGenerateGroup} /> : null}
        {batch ? <SupplementBatchCard batch={batch} values={batchValues} onChange={(id, value) => setBatchValues((current) => ({ ...current, [id]: value }))} onUseSuggestion={(id, value) => setBatchValues((current) => ({ ...current, [id]: value }))} onAISuggest={handleAISuggest} aiLoading={activeJob?.job_type === "supplement_batch_ai_fill"} onClose={() => setBatch(null)} onApply={async () => { try { const result = await applySupplementBatch(project.project_id, batch.batch_id, batchValues, false); const affected = Array.isArray(result.affected_node_ids) ? result.affected_node_ids.map(String) : []; toast.success(`已回填 ${affected.length} 个章节`); if (affected.length && window.confirm("待补信息已回映。是否现在重新生成这些章节的正文？")) { await startJob("chapter_batch_generation", { node_ids: affected }); toast.success("章节更新任务已提交") } } catch (err) { toast.error(err instanceof Error ? err.message : "回填失败") } }} /> : null}
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
              description="可先载入当前已生成内容，也可在合并完成后载入正式合并稿。"
              action={
                <Button variant="outline" onClick={loadCurrent} loading={loadingDoc} icon={<FileDown className="h-4 w-4" />}>
                  查看当前已生成内容
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
  const issues = collectAuditIssues(report)
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
        {issues.length ? <ul className="space-y-2">{issues.slice(0, 8).map((issue, index) => <li key={`${index}-${issue}`} className="flex items-start gap-2 rounded-[var(--radius)] border border-border p-2.5 text-xs leading-relaxed text-foreground"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-warning)]" />{issue}</li>)}</ul> : <p className="flex items-center gap-2 text-sm text-[var(--color-success)]"><CheckCircle2 className="h-4 w-4" />未发现需要立即处理的问题</p>}
        <details><summary className="cursor-pointer text-xs font-medium text-primary">技术详情</summary><pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius)] bg-muted/50 p-3 text-xs text-foreground">{JSON.stringify(report, null, 2)}</pre></details>
      </div>
    </Card>
  )
}

function GroupRecommendationCard({ recommendation, onGenerateGroup }: { recommendation: Record<string, unknown>; onGenerateGroup: (group: Record<string, unknown>) => Promise<void> }) {
  const groups = Array.isArray(recommendation.groups) ? recommendation.groups as Array<Record<string, unknown>> : []
  return <Card className="p-5"><SectionTitle title="AI 联合生成建议" description="建议只作为调度参考，各章节仍独立校验事实和版本。" /><div className="mt-3 space-y-2">{groups.length ? groups.map((group) => <div key={String(group.group_id)} className="rounded border border-border p-3"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium text-foreground">{String(group.title || "未命名组合")}</p><p className="mt-1 text-xs text-foreground">{(Array.isArray(group.node_titles) ? group.node_titles : []).map(String).join("、")}</p></div><Button size="sm" variant="outline" onClick={() => void onGenerateGroup(group)}>生成这组</Button></div><p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{String(group.reason || group.caution || "")}</p></div>) : <p className="text-xs text-muted-foreground">暂未找到适合联合生成的章节，建议按章节分别生成。</p>}</div></Card>
}

function SupplementBatchCard({ batch, values, onChange, onUseSuggestion, onAISuggest, aiLoading, onClose, onApply }: { batch: SupplementBatch; values: Record<string, string>; onChange: (id: string, value: string) => void; onUseSuggestion: (id: string, value: string) => void; onAISuggest: () => Promise<void>; aiLoading: boolean; onClose: () => void; onApply: () => Promise<void> }) {
  return <Card className="fixed inset-y-4 right-4 z-40 flex w-[min(680px,calc(100vw-32px))] flex-col p-5 shadow-2xl"><div className="flex items-start justify-between gap-3"><SectionTitle title="项目待补信息表单" description={`${batch.items.length} 项，已按关联章节合并`} /><Button size="icon" variant="ghost" onClick={onClose} aria-label="关闭"><span aria-hidden>×</span></Button></div><div className="mt-3 flex-1 space-y-3 overflow-y-auto">{batch.items.map((item) => <label key={item.item_id} className="block rounded border border-border p-3"><span className="text-xs font-medium text-foreground">{item.label}</span><span className="mt-1 block text-[10px] text-muted-foreground">关联：{item.node_titles.join("、")}</span>{item.ai_suggestion ? <button type="button" className="mt-2 text-left text-[11px] text-primary hover:underline" onClick={() => onUseSuggestion(item.item_id, item.ai_suggestion || "")}>AI建议：{item.ai_suggestion}（点击采用）</button> : null}<textarea className="mt-2 min-h-16 w-full rounded border border-border bg-background px-2 py-1.5 text-xs" value={values[item.item_id] || ""} onChange={(event) => onChange(item.item_id, event.target.value)} placeholder="可填写确认内容；留空则不回填" /></label>)}</div><div className="mt-3 flex flex-wrap justify-end gap-2 border-t border-border pt-3"><Button variant="outline" onClick={() => void onAISuggest()} loading={aiLoading}>让 AI 提建议</Button><Button variant="outline" onClick={onClose}>稍后处理</Button><Button onClick={() => void onApply()}>保存并回映章节</Button></div></Card>
}

function collectAuditIssues(report: Record<string, unknown>): string[] {
  const output: string[] = []
  const visit = (value: unknown, key = "") => {
    if (output.length >= 20) return
    if (typeof value === "string" && value.trim() && /(issue|problem|warning|missing|gap|建议|缺失|问题|风险)/i.test(`${key} ${value}`)) output.push(value.trim())
    else if (Array.isArray(value)) value.forEach((item) => visit(item, key))
    else if (value && typeof value === "object") Object.entries(value as Record<string, unknown>).forEach(([childKey, child]) => visit(child, childKey))
  }
  visit(report)
  return [...new Set(output)]
}
