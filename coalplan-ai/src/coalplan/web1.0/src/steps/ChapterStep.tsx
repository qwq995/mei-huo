import { useEffect, useMemo, useRef, useState } from "react"
import { AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpenCheck, BrainCircuit, CheckCircle2, ChevronRight, Database, FileEdit, FileText, GitBranch, History, Layers3, Pencil, Plus, Save, Search, Settings2, Sparkles, Trash2, Wand2, X } from "lucide-react"
import {
  applyChapterProposal,
  applyChapterPlanProposal,
  addSupplement,
  confirmVersionReview,
  createManualVersion,
  getChapterGenerationPreflight,
  getChapterBasisPreferences,
  generateChapterWritingSkill,
  getChapter,
  getSourceSection,
  listReferenceAtoms,
  listOutlineNodes,
  listChapterTasks,
  listChapterPlanProposals,
  listChapterProposals,
  listVersions,
  rejectChapterProposal,
  rejectChapterPlanProposal,
  saveChapterGenerationPlan,
  saveChapterBasisPreferences,
  saveChapterWritingSkill,
  selectVersion,
  type ChapterResponse,
  type ChapterGenerationPreflight,
  type ChapterGenerationPlan,
  type SourceSection,
  type SourceEvidenceSpan,
  type ReferenceAtomDetail,
  type ChapterVersion,
  type AIProposal,
  type ChapterTaskSummary,
  type OutlineNode,
  type ProjectResponse,
  type ChapterBasisPreferences,
} from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, LoadingBlock, SectionTitle, StatusBadge, TextArea, TextInput } from "@/components/ui"
import { Markdown } from "@/components/Markdown"
import MdEditor from "react-markdown-editor-lite"
import "react-markdown-editor-lite/lib/index.css"
import MarkdownIt from "markdown-it"
import { AttachmentPanel } from "@/steps/AttachmentPanel"
import { cn, formatDateTime } from "@/lib/utils"
import { useJobs } from "@/components/Jobs"

function getRenderableNodes(nodes: OutlineNode[]): OutlineNode[] {
  const parentIds = new Set(nodes.map((n) => n.parent_id).filter(Boolean) as string[])
  const leaves = nodes.filter((n) => n.enabled !== false && !parentIds.has(n.node_id))
  return leaves.length ? leaves : nodes.filter((n) => n.enabled !== false)
}

export function ChapterStep({ project, onNext }: { project: ProjectResponse; onNext: () => void }) {
  const outline = useAsyncData<OutlineNode[]>(() => listOutlineNodes(project.project_id), [project.project_id])
  const tasks = useAsyncData<ChapterTaskSummary[]>(() => listChapterTasks(project.project_id), [project.project_id])
  const [activeNode, setActiveNode] = useState<OutlineNode | null>(null)
  const [filter, setFilter] = useState<"all" | "pending" | "generated" | "attention">("all")
  const nodes = useMemo(() => getRenderableNodes(outline.data ?? []), [outline.data])
  const taskByNode = useMemo(() => new Map((tasks.data ?? []).map((task) => [task.node_id, task])), [tasks.data])
  const filteredNodes = useMemo(() => nodes.filter((node) => {
    const status = taskByNode.get(node.node_id)?.status ?? "pending"
    if (filter === "pending") return status === "pending"
    if (filter === "generated") return ["passed", "completed"].includes(status)
    if (filter === "attention") return ["failed", "needs_repair"].includes(status)
    return true
  }), [filter, nodes, taskByNode])

  useEffect(() => {
    if (!activeNode && nodes.length) {
      const first = nodes.find((node) => ["failed", "needs_repair", "pending"].includes(taskByNode.get(node.node_id)?.status ?? "pending")) ?? nodes[0]
      setActiveNode(first)
    }
  }, [activeNode, nodes, taskByNode])

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === project.project_id && ["chapter_generation", "child_chapter_generation", "project_generation"].includes(job?.job_type)) void tasks.reload()
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [project.project_id, tasks.reload])

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[300px_minmax(0,1fr)] xl:gap-6">
      <Card className="min-w-0 flex max-h-[calc(100vh-140px)] flex-col p-4 lg:sticky lg:top-20">
        <SectionTitle title="待生成章节" right={<span className="text-xs text-muted-foreground">{nodes.length}</span>} />
        <div className="mt-3 grid grid-cols-4 gap-1 rounded-[var(--radius)] border border-border p-1">
          {([['all','全部'],['pending','待生成'],['generated','已生成'],['attention','需处理']] as const).map(([value, label]) => <button key={value} onClick={() => setFilter(value)} className={cn("rounded-[calc(var(--radius)-2px)] px-1 py-1.5 text-[11px]", filter === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>{label}</button>)}
        </div>
        <div className="mt-3 flex-1 overflow-y-auto">
          {outline.loading ? (
            <LoadingBlock />
          ) : !nodes.length ? (
            <EmptyState icon={<FileEdit className="h-6 w-6" />} title="暂无章节" description="请先在上一步生成并确认目录。" />
          ) : (
            <ul className="flex flex-col gap-1">
              {filteredNodes.map((node) => {
                const isActive = activeNode?.node_id === node.node_id
                const task = taskByNode.get(node.node_id)
                return (
                  <li key={node.node_id}>
                    <button
                      onClick={() => setActiveNode(node)}
                      className={cn("flex w-full items-center gap-2 rounded-[var(--radius)] px-2.5 py-2 text-left text-sm transition-colors", isActive ? "bg-primary/[0.06] text-primary" : "text-foreground hover:bg-muted/60")}
                      style={{ paddingLeft: 10 + ((node.level ?? 1) - 1) * 10 }}
                    >
                      <span className="min-w-0 flex-1 truncate">{node.title || "未命名章节"}</span>
                      {task?.status === "passed" ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-success)]" /> : ["failed", "needs_repair"].includes(task?.status ?? "") ? <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[var(--color-warning)]" /> : null}
                      {node.target_word_count ? <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{node.target_word_count}</span> : null}
                      {isActive ? <ChevronRight className="h-4 w-4 shrink-0" /> : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        <Button className="mt-3 w-full" variant="outline" onClick={onNext} icon={<ArrowRight className="h-4 w-4" />}>
          合并与审查
        </Button>
      </Card>

      <div className="min-w-0">
        {activeNode ? (
          <ChapterWorkspace key={activeNode.node_id} project={project} node={activeNode} nodes={nodes} onSelect={setActiveNode} />
        ) : (
          <Card className="p-5">
            <EmptyState icon={<FileEdit className="h-8 w-8" />} title="选择章节开始撰写" description="左侧选择一个叶子章节，然后补充材料、生成正文、审阅版本。" />
          </Card>
        )}
      </div>
    </div>
  )
}

function ChapterWorkspace({ project, node, nodes, onSelect }: { project: ProjectResponse; node: OutlineNode; nodes: OutlineNode[]; onSelect: (node: OutlineNode) => void }) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const projectId = project.project_id
  const chapter = useAsyncData<ChapterResponse>(() => getChapter(projectId, node.node_id), [projectId, node.node_id])
  const versionsData = useAsyncData<ChapterVersion[]>(() => listVersions(projectId, node.node_id), [projectId, node.node_id])
  const preflight = useAsyncData<ChapterGenerationPreflight>(
    () => getChapterGenerationPreflight(projectId, node.node_id),
    [projectId, node.node_id],
  )
  const [generating, setGenerating] = useState(false)
  const [generatingChildren, setGeneratingChildren] = useState(false)
  const [openModule, setOpenModule] = useState<"plan" | "basis" | "source" | "edit" | "versions" | "attachments" | "supplements" | null>(null)
  const [focusWritingTask, setFocusWritingTask] = useState(false)
  const [reviewVersion, setReviewVersion] = useState<ChapterVersion | null>(null)
  const activeIndex = nodes.findIndex((item) => item.node_id === node.node_id)
  const currentJob = activeJob && String(activeJob.payload.node_id ?? "") === node.node_id ? activeJob : null

  const reloadAll = () => Promise.all([chapter.reload(), versionsData.reload()])

  const reviewLatestCandidate = async (selectedId = chapter.data?.version?.id) => {
    const items = await listVersions(projectId, node.node_id)
    const candidate = items.find((item) => item.status === "candidate" && item.id !== selectedId)
    if (candidate) setReviewVersion(candidate)
    await versionsData.reload()
  }

  const handleGenerate = async () => {
    if (!preflight.data?.readiness.can_generate) {
      toast.error(preflight.data?.readiness.message || "请先确认章节提纲和投标来源")
      return
    }
    setGenerating(true)
    try {
      await startJob("chapter_generation", { node_id: node.node_id })
      toast.success("章节生成已开始，完成后会自动保存为新版本")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    } finally {
      setGenerating(false)
    }
  }

  const handleGenerateChildren = async () => {
    setGeneratingChildren(true)
    try {
      await startJob("child_chapter_generation", { node_id: node.node_id, recursive: true, only_pending: true, limit: 8 })
      toast.success("子章节生成已开始，可在任务中心查看进度")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "子章节生成失败")
    } finally {
      setGeneratingChildren(false)
    }
  }

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === projectId && String(job?.payload?.node_id ?? "") === node.node_id) {
        void Promise.all([reloadAll(), preflight.reload(), reviewLatestCandidate()])
      }
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [node.node_id, preflight.reload, projectId])

  return (
    <div className="flex flex-col gap-5">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-lg font-semibold text-foreground">{node.title || "未命名章节"}</h2>
              <StatusBadge status={chapter.data?.status} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              目标字数 {node.target_word_count ?? "未设置"} · 节点 {node.node_id}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="icon" variant="ghost" disabled={activeIndex <= 0} onClick={() => onSelect(nodes[activeIndex - 1])} aria-label="上一章节"><ArrowLeft className="h-4 w-4" /></Button>
            <Button size="icon" variant="ghost" disabled={activeIndex < 0 || activeIndex >= nodes.length - 1} onClick={() => onSelect(nodes[activeIndex + 1])} aria-label="下一章节"><ArrowRight className="h-4 w-4" /></Button>
            <Button variant="outline" onClick={() => { setFocusWritingTask(true); setOpenModule("basis") }} icon={<Pencil className="h-4 w-4" />}>
              编辑本章写作任务
            </Button>
            <Button variant="accent" onClick={() => { setFocusWritingTask(false); setOpenModule("basis") }} icon={<Settings2 className="h-4 w-4" />}>
              管理本章生成依据
            </Button>
            <Button variant="outline" onClick={handleGenerateChildren} loading={generatingChildren} icon={<GitBranch className="h-4 w-4" />}>
              生成子章节
            </Button>
            <Button onClick={handleGenerate} loading={generating || Boolean(currentJob?.job_type === "chapter_generation")} disabled={!preflight.data?.readiness.can_generate || Boolean(activeJob && !currentJob)} icon={<Wand2 className="h-4 w-4" />}>
              {chapter.data?.markdown?.trim() ? "重新生成本章" : "生成本章"}
            </Button>
          </div>
        </div>
        {currentJob ? (
          <div className="mt-4 flex items-start gap-2 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
            <BrainCircuit className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div className="flex-1"><p className="font-medium text-foreground">{currentJob.message}</p><p className="mt-1">任务可在后台继续运行，您可以切换章节或页面；完成后系统会自动刷新版本。</p>{currentJob.total > 0 ? <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-[width]" style={{ width: `${Math.min(100, currentJob.current / currentJob.total * 100)}%` }} /></div> : null}</div>
          </div>
        ) : null}
      </Card>

      <div className="flex min-w-0 flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <WorkspaceModuleButton
            title="生成提纲"
            detail={preflight.data?.generation_plan?.status === "confirmed" ? "已确认，可直接生成" : "确认本章范围与生成要点"}
            status={preflight.data?.generation_plan?.status === "confirmed" ? "已确认" : "待确认"}
            onClick={() => setOpenModule("plan")}
          />
          <WorkspaceModuleButton
            title="生成依据"
            detail={`${preflight.data?.source_candidates.length ?? 0} 份投标来源 · ${preflight.data?.reference_atom_candidates.length ?? 0} 条原子 · ${preflight.data?.basis_preferences?.atom_ids.length ?? 0} 条已固定`}
            status={preflight.data?.readiness.can_generate ? "已就绪" : "需补充"}
            onClick={() => setOpenModule("basis")}
          />
          <WorkspaceModuleButton
            title="来源映射"
            detail={`${chapter.data?.source_mapping?.matches?.length ?? 0} 个匹配章节 · 点击查看原文`}
            status={chapter.data?.source_mapping?.matches?.length ? "已匹配" : "待查看"}
            onClick={() => setOpenModule("source")}
          />
          <WorkspaceModuleButton title="AI 修改" detail="按你的要求生成修改建议" status="可使用" onClick={() => setOpenModule("edit")} />
          <WorkspaceModuleButton title="待补信息" detail="逐条决定是否补充到项目资料" status={String(chapter.data?.source_mapping?.missing_evidence?.length ?? 0)} onClick={() => setOpenModule("supplements")} />
          <WorkspaceModuleButton title="版本记录" detail={`${versionsData.data?.length ?? 0} 个版本 · 可切换`} status={chapter.data?.version ? "已选用" : "暂无"} onClick={() => setOpenModule("versions")} />
          <WorkspaceModuleButton title="本章附件" detail="查看与补充本章材料" status="可查阅" onClick={() => setOpenModule("attachments")} />
        </div>
        <div className="text-[11px] text-muted-foreground">辅助模块已收起，点击上方入口即可编辑或查阅；正文始终保留在当前页面。</div>
        {chapter.loading ? (
          <Card className="p-5"><LoadingBlock label="加载章节内容..." /></Card>
        ) : (
          <ChapterEditor projectId={projectId} nodeId={node.node_id} nodeTitle={node.title} chapter={chapter.data} onChanged={reloadAll} />
        )}
      </div>
      {openModule === "plan" ? <WorkspaceDrawer title="生成前章节提纲" onClose={() => setOpenModule(null)}><ChapterPlanPanel projectId={projectId} nodeId={node.node_id} plan={preflight.data?.generation_plan ?? null} loading={preflight.loading} onChanged={() => void preflight.reload()} /></WorkspaceDrawer> : null}
      {openModule === "basis" ? <WorkspaceDrawer title="生成前依据预览" onClose={() => { setOpenModule(null); setFocusWritingTask(false) }}><GenerationBasisPanel projectId={projectId} preflight={preflight.data} loading={preflight.loading} focusWritingTask={focusWritingTask} onOpenSourceMapping={() => setOpenModule("source")} /></WorkspaceDrawer> : null}
      {openModule === "source" ? <WorkspaceDrawer title="来源映射" onClose={() => setOpenModule(null)}><SourcePanel projectId={projectId} chapter={chapter.data} loading={chapter.loading} /></WorkspaceDrawer> : null}
      {openModule === "edit" ? <WorkspaceDrawer title="AI 修改本章" onClose={() => setOpenModule(null)}><AIEditPanel projectId={projectId} nodeId={node.node_id} onApplied={() => reviewLatestCandidate()} /></WorkspaceDrawer> : null}
      {openModule === "supplements" ? <WorkspaceDrawer title="待补信息" onClose={() => setOpenModule(null)}><SupplementNeedsPanel projectId={projectId} nodeId={node.node_id} chapter={chapter.data} /></WorkspaceDrawer> : null}
      {openModule === "versions" ? <WorkspaceDrawer title="章节版本记录" onClose={() => setOpenModule(null)}><VersionPanel versions={versionsData.data ?? []} loading={versionsData.loading} selectedId={chapter.data?.version?.id ?? null} onReview={setReviewVersion} /></WorkspaceDrawer> : null}
      {openModule === "attachments" ? <WorkspaceDrawer title="本章附件" onClose={() => setOpenModule(null)}><AttachmentPanel projectId={projectId} nodeId={node.node_id} /></WorkspaceDrawer> : null}
      {reviewVersion ? <VersionCompareDrawer projectId={projectId} nodeId={node.node_id} current={chapter.data?.version ?? null} candidate={reviewVersion} onClose={() => setReviewVersion(null)} onSelected={async () => { setReviewVersion(null); await reloadAll() }} /> : null}
    </div>
  )
}

function WorkspaceModuleButton({ title, detail, status, onClick }: { title: string; detail: string; status: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group rounded-[var(--radius)] border border-border bg-card px-3.5 py-3 text-left transition-colors hover:border-primary/45 hover:bg-primary/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-foreground">{title}</span><span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">{status}</span></div>
      <p className="mt-1.5 truncate text-[11px] text-muted-foreground">{detail}</p>
      <span className="mt-2 inline-flex text-[11px] font-medium text-primary group-hover:underline">打开查看 <ChevronRight className="ml-0.5 h-3.5 w-3.5" /></span>
    </button>
  )
}

function WorkspaceDrawer({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-backdrop fixed inset-0 z-50 flex justify-end" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="glass-surface-strong flex h-full w-[min(720px,96vw)] flex-col rounded-l-[var(--radius)] border-y-0 border-r-0" role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-center justify-between gap-3 border-b border-border/80 px-5 py-4">
          <h2 className="text-base font-semibold text-foreground">{title}</h2>
          <Button size="icon" variant="ghost" onClick={onClose} aria-label="关闭窗口"><X className="h-4 w-4" /></Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">{children}</div>
      </aside>
    </div>
  )
}

function SupplementNeedsPanel({ projectId, nodeId, chapter }: { projectId: string; nodeId: string; chapter: ChapterResponse | null }) {
  const toast = useToast()
  const candidates = useMemo(() => {
    const fromMapping = chapter?.source_mapping?.missing_evidence ?? []
    const fromBody = Array.from((chapter?.markdown ?? "").matchAll(/【需人工补充：([^】]+)】/g)).map((match) => match[1].trim())
    return Array.from(new Set([...fromMapping, ...fromBody].filter(Boolean))).map((title, index) => ({ id: `need-${index}-${title}`, title }))
  }, [chapter?.markdown, chapter?.source_mapping?.missing_evidence])
  const [decisions, setDecisions] = useState<Record<string, { mode: "pending" | "manual" | "ai" | "ignore"; content: string }>>({})
  const [savingId, setSavingId] = useState<string | null>(null)

  const save = async (item: { id: string; title: string }) => {
    const decision = decisions[item.id] ?? { mode: "pending", content: "" }
    if (decision.mode === "pending") {
      toast.error("请先选择忽略、人工填写或交给 AI 建议")
      return
    }
    if (decision.mode === "manual" && !decision.content.trim()) {
      toast.error("请填写这条补充信息")
      return
    }
    setSavingId(item.id)
    try {
      await addSupplement(projectId, nodeId, {
        kind: decision.mode === "ai" ? "ai_request" : decision.mode === "ignore" ? "ignored_manual_requirement" : "text",
        title: item.title,
        content: decision.mode === "ignore" ? "本次不纳入生成，保留为已确认忽略项。" : decision.content.trim() || `请根据项目资料补充：${item.title}`,
        must_include: decision.mode !== "ignore",
      })
      toast.success(decision.mode === "ignore" ? "已记录为忽略项" : "待补信息已保存")
      setDecisions((current) => ({ ...current, [item.id]: { ...decision, mode: "pending", content: "" } }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存待补信息失败")
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded border border-primary/15 bg-primary/[0.03] p-3 text-xs leading-relaxed text-muted-foreground">这些内容不会写入生成正文。逐条选择处理方式后，系统会作为独立补充材料保存；AI 建议会在后续生成或修改时作为输入。</div>
      {!candidates.length ? <EmptyState title="暂无自动识别的待补信息" description="你仍可以在“本章附件”中手动新增补充材料。" /> : <div className="flex flex-col gap-3">
        {candidates.map((item) => {
          const decision = decisions[item.id] ?? { mode: "pending" as const, content: "" }
          return <div key={item.id} className="rounded border border-border bg-card p-3">
            <p className="text-sm font-medium text-foreground">{item.title}</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {([['manual', '人工填写'], ['ai', '交给 AI 建议'], ['ignore', '本次忽略']] as const).map(([mode, label]) => <button type="button" key={mode} onClick={() => setDecisions((current) => ({ ...current, [item.id]: { ...decision, mode } }))} className={cn("rounded border px-2.5 py-2 text-xs", decision.mode === mode ? "border-primary bg-primary/[0.06] text-primary" : "border-border text-muted-foreground hover:bg-muted")}>{label}</button>)}
            </div>
            {decision.mode === "manual" ? <TextArea className="mt-3" rows={3} value={decision.content} onChange={(event) => setDecisions((current) => ({ ...current, [item.id]: { ...decision, content: event.target.value } }))} placeholder="填写参数、图纸编号、审批结论、现场实测值等" /> : null}
            {decision.mode === "ai" ? <TextArea className="mt-3" rows={2} value={decision.content} onChange={(event) => setDecisions((current) => ({ ...current, [item.id]: { ...decision, content: event.target.value } }))} placeholder="可补充 AI 的处理要求，例如：仅依据已上传图纸提取，不要猜测参数" /> : null}
            <div className="mt-3 flex justify-end"><Button size="sm" onClick={() => void save(item)} loading={savingId === item.id}>保存这条处理</Button></div>
          </div>
        })}
      </div>}
    </div>
  )
}

function ChapterPlanPanel({ projectId, nodeId, plan, loading, onChanged }: { projectId: string; nodeId: string; plan: ChapterGenerationPlan | null; loading: boolean; onChanged: () => void }) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const [draft, setDraft] = useState<ChapterGenerationPlan | null>(plan ? clonePlan(plan) : null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const [aiPrompt, setAiPrompt] = useState("")
  const [proposal, setProposal] = useState<AIProposal | null>(null)
  const planJob = activeJob?.job_type === "chapter_plan_proposal" && String(activeJob.payload.node_id ?? "") === nodeId ? activeJob : null

  useEffect(() => {
    if (!dirty && plan) setDraft(clonePlan(plan))
  }, [dirty, plan])

  const reloadProposal = async () => {
    try {
      const items = await listChapterPlanProposals(projectId, nodeId)
      setProposal(items[0] ?? null)
    } catch {
      setProposal(null)
    }
  }

  useEffect(() => {
    void reloadProposal()
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === projectId && job?.job_type === "chapter_plan_proposal" && String(job?.payload?.node_id ?? "") === nodeId) void reloadProposal()
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [nodeId, projectId])

  const update = (patch: Partial<ChapterGenerationPlan>) => {
    setDraft((current) => current ? { ...current, ...patch, status: "draft", source: "user" } : current)
    setDirty(true)
  }

  const updateItem = (index: number, patch: Partial<ChapterGenerationPlan["items"][number]>) => {
    if (!draft) return
    const items = draft.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)
    update({ items })
  }

  const moveItem = (index: number, direction: -1 | 1) => {
    if (!draft) return
    const target = index + direction
    if (target < 0 || target >= draft.items.length) return
    const items = [...draft.items]
    ;[items[index], items[target]] = [items[target], items[index]]
    update({ items: items.map((item, itemIndex) => ({ ...item, sort_order: itemIndex + 1 })) })
  }

  const save = async (status: "draft" | "confirmed") => {
    if (!draft) return
    setSaving(true)
    try {
      const saved = await saveChapterGenerationPlan(projectId, nodeId, { ...draft, status })
      setDraft(clonePlan(saved))
      setDirty(false)
      toast.success(status === "confirmed" ? "章节范围和要点已确认，可以生成" : "章节提纲草稿已保存")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存章节提纲失败")
    } finally {
      setSaving(false)
    }
  }

  const askAI = async () => {
    if (!aiPrompt.trim()) {
      toast.error("请说明希望怎样调整本章")
      return
    }
    try {
      await startJob("chapter_plan_proposal", { node_id: nodeId, suggestion: aiPrompt.trim() })
      toast.success("AI 正在分析章节范围，完成后会显示提纲对比")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "提交提纲优化失败")
    }
  }

  const applyProposal = async () => {
    if (!proposal) return
    try {
      await applyChapterPlanProposal(projectId, nodeId, proposal.id)
      setProposal(null)
      setDirty(false)
      toast.success("AI 建议已应用为提纲草稿，请审阅后确认")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "应用提纲建议失败")
    }
  }

  const rejectProposal = async () => {
    if (!proposal) return
    try {
      await rejectChapterPlanProposal(projectId, nodeId, proposal.id)
      setProposal(null)
      toast.success("已忽略本次提纲建议")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "忽略提纲建议失败")
    }
  }

  if (loading || !draft) return <Card className="p-5"><LoadingBlock label="正在形成本章结构化提纲..." /></Card>
  const proposalPlan = proposal?.preview?.plan as ChapterGenerationPlan | undefined
  return <Card className="overflow-hidden">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
      <div>
        <div className="flex items-center gap-2"><p className="text-sm font-semibold text-foreground">生成前章节提纲</p><span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", draft.status === "confirmed" && !dirty ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800")}>{draft.status === "confirmed" && !dirty ? "已确认" : dirty ? "有未保存修改" : "待确认"}</span></div>
        <p className="mt-1 text-xs text-muted-foreground">先界定本章写什么、不写什么，再让系统匹配证据和原子。生成会严格按已确认提纲分单元执行。</p>
      </div>
      <Button size="sm" variant="ghost" onClick={() => setExpanded((value) => !value)}>{expanded ? "收起" : "展开编辑"}</Button>
    </div>
    {expanded ? <div className="space-y-4 px-5 py-4">
      <div><label className="mb-1.5 block text-xs font-medium text-foreground">本章范围</label><TextArea rows={2} value={draft.scope_statement} onChange={(event) => update({ scope_statement: event.target.value })} placeholder="说明本章负责交代的对象、条件和控制范围" /></div>
      <div>
        <div className="mb-2 flex items-center justify-between"><p className="text-xs font-medium text-foreground">生成要点与顺序</p><Button size="sm" variant="outline" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => update({ items: [...draft.items, { item_id: `planitem_${Date.now()}`, title: "新增要点", purpose: "", key_points: [], evidence_requirement: "项目事实需有投标证据或人工确认", output_form: "形成可直接入稿的小节", target_word_count: 450, enabled: true, sort_order: draft.items.length + 1 }] })}>新增要点</Button></div>
        <div className="space-y-2">{draft.items.map((item, index) => <div key={item.item_id} className={cn("rounded border p-3", item.enabled ? "border-border bg-card" : "border-border bg-muted/35 opacity-70")}>
          <div className="flex items-center gap-2"><input type="checkbox" checked={item.enabled} onChange={(event) => updateItem(index, { enabled: event.target.checked })} aria-label="是否生成该要点" /><span className="w-5 text-center text-xs font-semibold text-primary">{index + 1}</span><TextInput value={item.title} onChange={(event) => updateItem(index, { title: event.target.value })} className="h-8 flex-1" /><Button size="icon" variant="ghost" disabled={index === 0} onClick={() => moveItem(index, -1)} aria-label="上移要点"><ArrowUp className="h-3.5 w-3.5" /></Button><Button size="icon" variant="ghost" disabled={index === draft.items.length - 1} onClick={() => moveItem(index, 1)} aria-label="下移要点"><ArrowDown className="h-3.5 w-3.5" /></Button><Button size="icon" variant="ghost" onClick={() => update({ items: draft.items.filter((_, itemIndex) => itemIndex !== index) })} aria-label="删除要点"><Trash2 className="h-3.5 w-3.5" /></Button></div>
          <div className="mt-2 grid gap-2 md:grid-cols-2"><TextArea rows={2} value={item.purpose} onChange={(event) => updateItem(index, { purpose: event.target.value })} placeholder="这个要点要解决什么问题" /><TextArea rows={2} value={item.key_points.join("\n")} onChange={(event) => updateItem(index, { key_points: lines(event.target.value) })} placeholder="每行一个具体内容点" /><TextArea rows={2} value={item.evidence_requirement} onChange={(event) => updateItem(index, { evidence_requirement: event.target.value })} placeholder="需要哪些项目证据" /><div className="grid grid-cols-[1fr_110px] gap-2"><TextInput value={item.output_form} onChange={(event) => updateItem(index, { output_form: event.target.value })} placeholder="输出形式" /><TextInput type="number" value={item.target_word_count ?? ""} onChange={(event) => updateItem(index, { target_word_count: Number(event.target.value) || null })} placeholder="字数" /></div></div>
        </div>)}</div>
      </div>
      <div className="grid gap-3 md:grid-cols-2"><div><label className="mb-1.5 block text-xs font-medium text-foreground">明确不写入本章</label><TextArea rows={4} value={draft.out_of_scope.join("\n")} onChange={(event) => update({ out_of_scope: lines(event.target.value) })} placeholder="每行一个越界主题" /></div><div><label className="mb-1.5 block text-xs font-medium text-foreground">待项目人员补充</label><TextArea rows={4} value={draft.manual_inputs.join("\n")} onChange={(event) => update({ manual_inputs: lines(event.target.value) })} placeholder="参数、图纸、批复、监测值等" /></div></div>
      <div className="rounded border border-primary/15 bg-primary/[0.03] p-3"><p className="text-xs font-medium text-foreground">让 AI 按你的思路优化提纲</p><div className="mt-2 flex flex-col gap-2 sm:flex-row"><TextArea rows={2} value={aiPrompt} onChange={(event) => setAiPrompt(event.target.value)} placeholder="例如：本章只说明气候与水文条件及其施工影响，不展开完整安全体系；补充雨季监测和停复工闭环。" className="flex-1" /><Button variant="accent" onClick={() => void askAI()} loading={Boolean(planJob)} icon={<Sparkles className="h-4 w-4" />}>生成优化建议</Button></div>{planJob ? <p className="mt-2 text-[11px] text-primary">{planJob.message}</p> : null}</div>
      {proposalPlan ? <div className="rounded border border-accent/30 bg-accent/[0.04] p-3"><div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-accent">AI 提纲建议，尚未应用</p><span className="text-[10px] text-muted-foreground">{proposalPlan.items?.filter((item) => item.enabled).length ?? 0} 个生成要点</span></div><p className="mt-2 text-xs leading-relaxed text-foreground">{proposalPlan.scope_statement}</p><ol className="mt-2 space-y-1">{proposalPlan.items?.filter((item) => item.enabled).map((item, index) => <li key={item.item_id} className="text-[11px] leading-relaxed text-foreground">{index + 1}. {item.title}：{item.purpose}</li>)}</ol><div className="mt-3 flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => void rejectProposal()}>忽略</Button><Button size="sm" onClick={() => void applyProposal()}>应用为草稿</Button></div></div> : null}
      <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3"><Button variant="outline" onClick={() => { setDraft(clonePlan(plan)); setDirty(false) }} disabled={!dirty}>放弃修改</Button><Button variant="outline" loading={saving} onClick={() => void save("draft")} icon={<Save className="h-4 w-4" />}>保存草稿</Button><Button loading={saving} onClick={() => void save("confirmed")} icon={<CheckCircle2 className="h-4 w-4" />}>确认并用于生成</Button></div>
    </div> : null}
  </Card>
}

function clonePlan(plan: ChapterGenerationPlan | null): ChapterGenerationPlan | null {
  return plan ? JSON.parse(JSON.stringify(plan)) as ChapterGenerationPlan : null
}

function buildWritingTaskSeed(preflight: ChapterGenerationPreflight | null): Record<string, unknown> {
  const writingSkill = preflight?.writing_skill
  return {
    mission: writingSkill?.chapter_role || "围绕当前章节组织可验证的施工组织设计内容",
    task_types: writingSkill?.task_types?.length ? writingSkill.task_types : (writingSkill?.structure ?? []),
    organization_logic: writingSkill?.structure ?? [],
    control_loops: writingSkill?.control_loops ?? [],
    required_inputs: writingSkill?.required_inputs ?? [],
    domain_variants: writingSkill?.domain_variants ?? [],
    coverage_plan: [],
    evidence_rules: writingSkill?.required_inputs ?? ["项目事实必须来自投标证据或人工确认"],
    fact_boundary_rules: ["不得编造项目参数、工程量、地名和日期"],
    avoid: [],
  }
}

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function GenerationBasisPanel({ projectId, preflight, loading, focusWritingTask = false, onOpenSourceMapping }: { projectId: string; preflight: ChapterGenerationPreflight | null; loading: boolean; focusWritingTask?: boolean; onOpenSourceMapping: () => void }) {
  const toast = useToast()
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const [sourceSection, setSourceSection] = useState<SourceSection | null>(null)
  const [atom, setAtom] = useState<ReferenceAtomDetail | null>(null)
  const [skill, setSkill] = useState<{ title: string; content: string[] } | null>(null)
  const [skillKind, setSkillKind] = useState<"task" | "technique">("technique")
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null)
  const [chapterSkill, setChapterSkill] = useState<Record<string, unknown> | null>(preflight?.chapter_writing_skill ?? null)
  const [skillLoading, setSkillLoading] = useState(false)
  const [preferences, setPreferences] = useState<ChapterBasisPreferences | null>(null)
  const [managerOpen, setManagerOpen] = useState(false)
  const [managerTab, setManagerTab] = useState<"atoms" | "skills">("atoms")
  const [allAtoms, setAllAtoms] = useState<ReferenceAtomDetail[]>([])
  const [atomsLoading, setAtomsLoading] = useState(false)
  const [basisSaving, setBasisSaving] = useState(false)
  const [skillEditorOpen, setSkillEditorOpen] = useState(false)
  const [skillSaving, setSkillSaving] = useState(false)

  useEffect(() => setChapterSkill(preflight?.chapter_writing_skill ?? null), [preflight?.chapter_writing_skill])
  useEffect(() => {
    if (!preflight) return
    setPreferences(preflight.basis_preferences ?? { node_id: preflight.node_id, atom_ids: [], excluded_atom_ids: [], skill_keys: [], prompt: "" })
  }, [preflight])

  const openManager = async (tab: "atoms" | "skills") => {
    setManagerTab(tab)
    setManagerOpen(true)
    if (tab === "atoms" && !allAtoms.length) {
      setAtomsLoading(true)
      try { setAllAtoms(await listReferenceAtoms("published")) } catch (err) { toast.error(err instanceof Error ? err.message : "读取原子库失败") } finally { setAtomsLoading(false) }
    }
  }

  const savePreferences = async (next: ChapterBasisPreferences) => {
    setBasisSaving(true)
    try {
      const saved = await saveChapterBasisPreferences(projectId, next.node_id, { atom_ids: next.atom_ids, excluded_atom_ids: next.excluded_atom_ids, skill_keys: next.skill_keys, prompt: next.prompt })
      setPreferences(saved)
      setManagerOpen(false)
      toast.success("本章依据已保存到当前项目")
    } catch (err) { toast.error(err instanceof Error ? err.message : "保存依据配置失败") } finally { setBasisSaving(false) }
  }

  const openSource = async (sectionId: string) => {
    setLoadingDetailId(sectionId)
    try {
      setSourceSection(await getSourceSection(projectId, sectionId))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "读取来源内容失败")
    } finally {
      setLoadingDetailId(null)
    }
  }

  const openAtom = async (atomId: string) => {
    setLoadingDetailId(atomId)
    try {
      const match = (await listReferenceAtoms()).find((item) => item.id === atomId)
      if (!match) throw new Error("未找到该原子要素")
      setAtom(match)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "读取原子内容失败")
    } finally {
      setLoadingDetailId(null)
    }
  }

  const generateSkill = async () => {
    setSkillLoading(true)
    try {
      if (!preflight) return
      setChapterSkill(await generateChapterWritingSkill(projectId, preflight.node_id))
      toast.success("章节专属写作 Skill 已生成")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成章节 Skill 失败")
    } finally {
      setSkillLoading(false)
    }
  }

  const saveSkill = async (value: Record<string, unknown>) => {
    if (!preflight) return
    setSkillSaving(true)
    try {
      const saved = await saveChapterWritingSkill(projectId, preflight.node_id, value)
      setChapterSkill(saved)
      toast.success("章节 Skill 已保存，后续生成将使用新规则")
    } catch (err) { toast.error(err instanceof Error ? err.message : "保存章节 Skill 失败") } finally { setSkillSaving(false) }
  }

  const editWritingTask = () => {
    const base = chapterSkill ?? buildWritingTaskSeed(preflight)
    const savedLines = Array.isArray(base.task_types) ? base.task_types.map(String).filter(Boolean) : []
    const fallbackLines = preflight?.writing_skill.task_types?.length ? preflight.writing_skill.task_types : (preflight?.writing_skill.structure ?? [])
    const taskLines = savedLines.length ? savedLines : fallbackLines.map(String).filter(Boolean)
    const seed = { ...base, task_types: taskLines }
    if (!chapterSkill) setChapterSkill(seed)
    setSkillKind("task")
    setSkill({ title: "本章写作任务", content: taskLines })
  }

  const editGeneratedSkill = () => {
    if (!chapterSkill) setChapterSkill(buildWritingTaskSeed(preflight))
    setSkillEditorOpen(true)
  }

  useEffect(() => {
    if (focusWritingTask && preflight && !loading) editWritingTask()
  }, [focusWritingTask, loading, preflight])

  if (loading) {
    return (
      <Card className="p-5">
        <LoadingBlock label="正在准备本章生成依据..." />
      </Card>
    )
  }
  if (!preflight) return null
  const savedTaskLines = Array.isArray(chapterSkill?.task_types) ? chapterSkill.task_types.map(String).filter(Boolean) : []
  const taskLines = savedTaskLines.length ? savedTaskLines : (preflight.writing_skill.task_types?.length ? preflight.writing_skill.task_types : preflight.writing_skill.structure)
  const techniqueLines = [...(preflight.writing_skill.matched_skill_keys ?? []), ...(preflight.writing_skill.control_loops ?? []), ...(preflight.writing_skill.domain_variants ?? [])]
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <p className="text-sm font-semibold text-foreground">生成前依据预览</p>
          <p className="mt-1 text-xs text-muted-foreground">{preflight.readiness.message}</p>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium", preflight.readiness.can_generate ? "bg-[color-mix(in_srgb,var(--color-success)_14%,transparent)] text-[var(--color-success)]" : "bg-[color-mix(in_srgb,var(--color-warning)_16%,transparent)] text-[var(--color-warning)]")}>
          {preflight.readiness.can_generate ? "依据已就绪" : preflight.readiness.has_source_candidates ? "待确认章节提纲" : "建议先补来源"}
        </span>
      </div>
      <div className="grid divide-y divide-border md:grid-cols-3 md:divide-x md:divide-y-0">
        <BasisColumn
          icon={<Database className="h-4 w-4" />}
          title="投标文档"
          role="决定本项目能写哪些事实"
          count={preflight.source_candidates.length}
          lines={preflight.source_candidates.map((item) => item.title_path.join(" / "))}
          items={preflight.source_candidates.map((item) => ({ id: item.section_id, label: item.title_path.join(" / "), summary: item.snippet }))}
          itemsOpen={openGroup === "source"}
          onToggleItems={() => setOpenGroup((value) => value === "source" ? null : "source")}
          onOpenItem={(item) => void openSource(item.id)}
          itemLabel="来源"
          actionLabel="打开来源映射"
          onAction={onOpenSourceMapping}
          loadingItemId={loadingDetailId}
          empty="尚无候选来源"
        />
        <BasisColumn
          icon={<BookOpenCheck className="h-4 w-4" />}
          title="优质原子"
          role="补充工序与控制闭环，不迁移参数"
          count={preflight.reference_atom_candidates.length}
          lines={preflight.reference_atom_candidates.map((item) => `${item.process || item.title_path[item.title_path.length - 1] || "未标注工艺"} · ${item.project_name}`)}
          items={preflight.reference_atom_candidates.map((item) => ({ id: item.atom_id, label: item.title_path.join(" / ") || item.process || "未标注原子", summary: `${item.project_name} · ${item.process || "未标注工艺"} · 质量评分 ${(item.quality_score * 100).toFixed(0)}%` }))}
          itemsOpen={openGroup === "atom"}
          onToggleItems={() => setOpenGroup((value) => value === "atom" ? null : "atom")}
          onOpenItem={(item) => void openAtom(item.id)}
          itemLabel="原子要素"
          actionLabel={`管理选择${preferences?.atom_ids.length ? ` · 已选 ${preferences.atom_ids.length}` : ""}`}
          onAction={() => void openManager("atoms")}
          loadingItemId={loadingDetailId}
          empty="本章不强行使用原子"
        />
        <div className="min-w-0 divide-y divide-border">
          <BasisColumn
            icon={<FileEdit className="h-4 w-4" />}
            title="本章写作任务"
            role="规定本章需要交代什么内容"
            count={taskLines.length}
            lines={taskLines}
            items={[{ id: "chapter-writing-task", label: "本章写作任务", summary: taskLines.join("；") }]}
            itemsOpen={openGroup === "task"}
            onToggleItems={() => setOpenGroup((value) => value === "task" ? null : "task")}
            onOpenItem={() => { setSkillKind("task"); setSkill({ title: "本章写作任务", content: taskLines }); setOpenGroup("task") }}
            itemLabel="写作任务"
            actionLabel="编辑本章写作任务"
            onAction={editWritingTask}
            empty="尚未形成章节写作任务"
          />
          <BasisColumn
            icon={<BrainCircuit className="h-4 w-4" />}
            title="写作技巧"
            role="规定如何组织、展开和控制表达"
            count={techniqueLines.length}
            lines={techniqueLines}
            items={techniqueLines.map((item, index) => ({ id: `skill-${index}-${item}`, label: item, summary: "仅影响结构、工艺展开和表达方式，不提供项目事实" }))}
            itemsOpen={openGroup === "skill"}
            onToggleItems={() => setOpenGroup((value) => value === "skill" ? null : "skill")}
            onOpenItem={(item) => { setSkillKind("technique"); setSkill({ title: "写作技巧", content: [item.label] }); setOpenGroup("skill") }}
            itemLabel="写作技巧"
            actionLabel="管理技巧"
            onAction={() => void openManager("skills")}
            empty="尚未匹配写作技巧"
          />
        </div>
      </div>
      <div className="border-t border-border px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-foreground">章节专属 AI Writing Skill</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">根据项目概况、全局重点和本章来源生成的写作指挥规则，用于控制要点覆盖、组织顺序和事实边界。</p>
          </div>
          <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void generateSkill()} loading={skillLoading} icon={<Sparkles className="h-3.5 w-3.5" />}>
            {chapterSkill ? "重新生成" : "AI 生成 Skill"}
          </Button><Button size="sm" variant="outline" onClick={editGeneratedSkill} icon={<Pencil className="h-3.5 w-3.5" />}>编辑 AI Skill</Button></div>
        </div>
        {chapterSkill ? <ChapterSkillSummary skill={chapterSkill} /> : <p className="mt-3 rounded border border-dashed border-border px-3 py-2 text-[11px] text-muted-foreground">尚未生成章节专属 Skill。正式生成章节时会自动创建。</p>}
      </div>
      <div className="border-t border-border px-5 py-4">
        <p className="flex items-center gap-2 text-xs font-semibold text-foreground">
          <Layers3 className="h-4 w-4 text-primary" />
          本章将分 {preflight.writing_units.length} 次细粒度生成
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {preflight.writing_units.map((unit) => (
            <div key={unit.unit_id} className="flex items-start justify-between gap-3 border-l-2 border-primary/30 pl-3">
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-foreground">{unit.sequence}. {unit.title}</p>
                <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{unit.writing_topics.slice(0, 3).join(" · ")}</p>
              </div>
              <span className="shrink-0 text-[11px] text-muted-foreground">约 {unit.target_word_count} 字</span>
            </div>
          ))}
        </div>
      </div>
      {sourceSection ? <SourceSectionModal section={sourceSection} focusedEvidence={null} onClose={() => setSourceSection(null)} /> : null}
      {atom ? <BasisDetailModal title={atom.title_path.join(" / ")} subtitle={`${atom.project_name} · ${atom.process || "未标注工艺"} · ${atom.status}`} content={atom.content} meta={`原子 ${atom.id} · 原文第 ${atom.start_line}-${atom.end_line} 行`} onClose={() => setAtom(null)} /> : null}
      {skill ? <BasisDetailModal title={skill.title} subtitle={skillKind === "task" ? "本章写作任务 · 规定本章需要写什么" : "写作技巧 · 规定如何组织、展开和表达"} content={skill.content.join("\n")} meta={skillKind === "task" ? "任务清单可编辑保存；项目事实仍以投标依据为准" : "写作规则不提供项目事实"} onClose={() => setSkill(null)} editableLines={skillKind === "task" ? skill.content : undefined} onSaveLines={skillKind === "task" ? async (lines) => { const next = { ...(chapterSkill ?? buildWritingTaskSeed(preflight)), task_types: lines }; await saveSkill(next) } : undefined} saving={skillSaving} editLabel="编辑本章写作任务" startEditing={skillKind === "task"} /> : null}
      {managerOpen && preferences ? <BasisManagerModal
        tab={managerTab}
        atoms={allAtoms}
        candidates={preflight.reference_atom_candidates.map((item) => item.atom_id)}
        skills={[...new Set([...(preflight.writing_skill.matched_skill_keys ?? []), ...(preflight.writing_skill.task_types ?? [])])]}
        preferences={preferences}
        loading={atomsLoading}
        saving={basisSaving}
        onClose={() => setManagerOpen(false)}
        onSave={(next) => void savePreferences(next)}
      /> : null}
      {skillEditorOpen ? <WritingSkillEditorModal skill={chapterSkill ?? buildWritingTaskSeed(preflight)} saving={skillSaving} onClose={() => setSkillEditorOpen(false)} onSave={(value) => void saveSkill(value)} /> : null}
    </Card>
  )
}

function ChapterSkillSummary({ skill }: { skill: Record<string, unknown> }) {
  const list = (value: unknown) => Array.isArray(value) ? value.filter(Boolean).map(String) : []
  const coverage = Array.isArray(skill.coverage_plan) ? skill.coverage_plan as Array<Record<string, unknown>> : []
  return <div className="mt-3 grid gap-2 sm:grid-cols-2">
    <div className="rounded border border-primary/15 bg-primary/[0.03] px-3 py-2 sm:col-span-2"><p className="text-[10px] font-medium text-primary">章节任务</p><p className="mt-1 text-xs leading-relaxed text-foreground">{String(skill.mission || "围绕当前章节组织可验证的施组内容")}</p></div>
    <div className="rounded border border-border px-3 py-2"><p className="text-[10px] font-medium text-muted-foreground">组织逻辑</p><ul className="mt-1 space-y-1">{list(skill.organization_logic).slice(0, 5).map((item) => <li key={item} className="text-[11px] leading-relaxed text-foreground">{item}</li>)}</ul></div>
    <div className="rounded border border-border px-3 py-2"><p className="text-[10px] font-medium text-muted-foreground">要点覆盖</p><ul className="mt-1 space-y-1">{coverage.slice(0, 6).map((item, index) => <li key={`${String(item.topic)}-${index}`} className="text-[11px] leading-relaxed text-foreground">{String(item.topic || "未命名要点")}：{String(item.purpose || "按章节职责展开")}</li>)}</ul></div>
    <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 sm:col-span-2"><p className="text-[10px] font-medium text-amber-800">生成约束</p><p className="mt-1 text-[11px] leading-relaxed text-amber-900">{[...list(skill.evidence_rules), ...list(skill.fact_boundary_rules), ...list(skill.avoid)].slice(0, 5).join("；") || "项目事实必须回到投标证据或人工确认"}</p></div>
  </div>
}

function BasisDetailModal({ title, subtitle, meta, content, onClose, onEdit, editLabel, editableLines, onSaveLines, saving, startEditing = false }: { title: string; subtitle: string; meta: string; content: string; onClose: () => void; onEdit?: () => void; editLabel?: string; editableLines?: string[]; onSaveLines?: (lines: string[]) => void | Promise<void>; saving?: boolean; startEditing?: boolean }) {
  const [editing, setEditing] = useState(startEditing)
  const [linesDraft, setLinesDraft] = useState<string[]>(editableLines ?? [])
  const [savingLines, setSavingLines] = useState(false)
  const canEditLines = Boolean(editableLines && onSaveLines)
  const saveLines = async () => {
    if (!onSaveLines) return
    setSavingLines(true)
    try { await onSaveLines(linesDraft.map((line) => line.trim()).filter(Boolean)); setEditing(false) } finally { setSavingLines(false) }
  }
  return <div className="modal-backdrop fixed inset-0 z-40 flex items-center justify-center p-4">
    <div className="flex max-h-[86vh] w-[min(900px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl">
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div className="min-w-0"><p className="truncate text-sm font-semibold text-foreground">{title}</p><p className="mt-1 text-xs text-muted-foreground">{subtitle}</p><p className="mt-1 text-[10px] text-primary">{meta}</p></div>
        <div className="flex shrink-0 items-center gap-2">{canEditLines ? <Button size="sm" variant="outline" onClick={() => setEditing(true)} icon={<Pencil className="h-3.5 w-3.5" />}>{editLabel ?? "编辑"}</Button> : onEdit ? <Button size="sm" variant="outline" onClick={() => { onClose(); onEdit() }} icon={<Pencil className="h-3.5 w-3.5" />}>{editLabel ?? "编辑"}</Button> : null}<button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭依据详情"><X className="h-4 w-4" /></button></div>
      </div>
      {editing ? <div className="min-h-0 flex-1 overflow-auto p-5"><p className="mb-3 text-xs leading-relaxed text-muted-foreground">逐项编辑本章需要完成的写作任务，可删除不需要的任务或新增任务。保存后会用于后续生成。</p><div className="space-y-2">{linesDraft.map((line, index) => <div key={`${index}-${line}`} className="flex items-center gap-2"><span className="w-5 shrink-0 text-center text-xs text-muted-foreground">{index + 1}</span><TextInput value={line} onChange={(event) => setLinesDraft((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} /><Button size="icon" variant="ghost" onClick={() => setLinesDraft((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label={`删除第 ${index + 1} 项写作任务`}><Trash2 className="h-4 w-4" /></Button></div>)}</div><Button size="sm" variant="outline" className="mt-3" onClick={() => setLinesDraft((current) => [...current, ""])} icon={<Plus className="h-3.5 w-3.5" />}>新增写作任务</Button><div className="mt-5 flex justify-end gap-2 border-t border-border pt-3"><Button size="sm" variant="outline" onClick={() => { setLinesDraft(editableLines ?? []); setEditing(false) }}>取消</Button><Button size="sm" loading={savingLines || saving} onClick={() => void saveLines()} icon={<Save className="h-3.5 w-3.5" />}>保存写作任务</Button></div></div> : <pre className="flex-1 overflow-auto whitespace-pre-wrap break-words p-5 text-[13px] leading-relaxed text-foreground">{content || "暂无可显示内容"}</pre>}
    </div>
  </div>
}

function WritingSkillEditorModal({ skill, saving, onClose, onSave }: { skill: Record<string, unknown>; saving: boolean; onClose: () => void; onSave: (value: Record<string, unknown>) => void }) {
  const list = (value: unknown) => Array.isArray(value) ? value.map(String).join("\n") : ""
  const [draft, setDraft] = useState({
    mission: String(skill.mission ?? ""),
    task_types: list(skill.task_types),
    organization_logic: list(skill.organization_logic),
    control_loops: list(skill.control_loops),
    required_inputs: list(skill.required_inputs),
    domain_variants: list(skill.domain_variants),
    evidence_rules: list(skill.evidence_rules),
    fact_boundary_rules: list(skill.fact_boundary_rules),
    avoid: list(skill.avoid),
  })
  const field = (key: keyof typeof draft, label: string, placeholder: string) => <label className="block"><span className="mb-1 block text-xs font-medium text-foreground">{label}</span><TextArea rows={3} value={draft[key]} onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))} placeholder={placeholder} /></label>
  const toLines = (value: string) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
  const save = () => onSave({ ...skill, mission: draft.mission.trim(), task_types: toLines(draft.task_types), organization_logic: toLines(draft.organization_logic), control_loops: toLines(draft.control_loops), required_inputs: toLines(draft.required_inputs), domain_variants: toLines(draft.domain_variants), evidence_rules: toLines(draft.evidence_rules), fact_boundary_rules: toLines(draft.fact_boundary_rules), avoid: toLines(draft.avoid) })
  return <div className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"><div className="glass-surface-strong flex max-h-[90vh] w-[min(860px,96vw)] flex-col rounded-[var(--radius)]"><div className="flex items-start justify-between gap-4 border-b border-border/80 px-5 py-4"><div><p className="text-sm font-semibold text-foreground">编辑 AI 写作技巧</p><p className="mt-1 text-xs text-muted-foreground">用普通文字编辑写作规则；每行一项，不需要编写 JSON。</p></div><button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭 AI 写作技巧编辑"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1 overflow-y-auto p-5"><div className="space-y-4"><label className="block"><span className="mb-1 block text-xs font-medium text-foreground">写作任务目标</span><TextArea rows={2} value={draft.mission} onChange={(event) => setDraft((current) => ({ ...current, mission: event.target.value }))} placeholder="例如：围绕工程地质条件说明施工影响、风险和应对要求" /></label>{field("organization_logic", "组织逻辑", "例如：先概述，再按施工阶段展开\n例如：每个工序都补充质量检查和记录")} {field("control_loops", "控制闭环", "例如：施工准备 -> 过程检查 -> 问题处置 -> 验收记录")} {field("required_inputs", "需要引用的输入", "例如：项目位置、主要工程量、设计图纸")} {field("domain_variants", "专业写法", "例如：突出隧洞开挖、支护和涌水风险")} {field("evidence_rules", "证据使用规则", "例如：所有项目参数必须回到投标文档")} {field("fact_boundary_rules", "事实边界", "例如：缺少依据的参数不得自行补写")} {field("avoid", "避免事项", "例如：避免泛泛而谈，避免照搬参考项目")}</div></div><div className="flex flex-wrap justify-end gap-2 border-t border-border/80 px-5 py-3"><Button size="sm" variant="outline" onClick={onClose}>取消</Button><Button size="sm" loading={saving} onClick={save} icon={<Save className="h-3.5 w-3.5" />}>保存 AI 写作技巧</Button></div></div></div>
}

function SkillEditorModal({ skill, saving, onClose, onSave }: { skill: Record<string, unknown>; saving: boolean; onClose: () => void; onSave: (value: Record<string, unknown>) => void }) {
  const [text, setText] = useState(JSON.stringify(skill, null, 2))
  const [error, setError] = useState("")
  return <div className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"><div className="glass-surface-strong flex max-h-[88vh] w-[min(900px,96vw)] flex-col rounded-[var(--radius)]"><div className="flex items-start justify-between border-b border-border/80 px-5 py-4"><div><p className="text-sm font-semibold text-foreground">编辑本章写作任务</p><p className="mt-1 text-xs text-muted-foreground">可修改任务目标、组织逻辑、控制闭环和事实边界；保存后作为本章生成规则使用。</p></div><button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭写作任务编辑"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1 overflow-auto p-5"><TextArea rows={22} value={text} onChange={(event) => { setText(event.target.value); setError("") }} className="font-mono text-[12px]" />{error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}</div><div className="flex justify-end gap-2 border-t border-border px-5 py-3"><Button size="sm" variant="outline" onClick={onClose}>取消</Button><Button size="sm" loading={saving} onClick={() => { try { const value = JSON.parse(text); if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("必须是 JSON 对象"); onSave(value as Record<string, unknown>) } catch (err) { setError(err instanceof Error ? err.message : "写作任务格式不正确") }}}>保存写作任务</Button></div></div></div>
}

function BasisManagerModal({
  tab, atoms, candidates, skills, preferences, loading, saving, onClose, onSave,
}: {
  tab: "atoms" | "skills"
  atoms: ReferenceAtomDetail[]
  candidates: string[]
  skills: string[]
  preferences: ChapterBasisPreferences
  loading: boolean
  saving: boolean
  onClose: () => void
  onSave: (preferences: ChapterBasisPreferences) => void
}) {
  const [draft, setDraft] = useState(preferences)
  const [currentTab, setCurrentTab] = useState(tab)
  const [query, setQuery] = useState("")
  const [customSkill, setCustomSkill] = useState("")
  const [index, setIndex] = useState("全部")
  const processIndexes = [...new Set(atoms.map((atom) => atom.process.trim()).filter(Boolean))].slice(0, 8)
  const visibleAtoms = atoms.filter((atom) => {
    const text = [atom.project_name, atom.project_type, atom.process, atom.specialty, atom.work_item, ...atom.title_path, atom.content].join(" ").toLowerCase()
    const matchesQuery = !query.trim() || text.includes(query.trim().toLowerCase())
    const matchesIndex = index === "全部" || atom.process === index
    return matchesQuery && matchesIndex
  })
  const toggleAtom = (id: string) => {
    const selected = draft.atom_ids.includes(id)
    setDraft({ ...draft, atom_ids: selected ? draft.atom_ids.filter((item) => item !== id) : [...draft.atom_ids, id], excluded_atom_ids: draft.excluded_atom_ids.filter((item) => item !== id) })
  }
  const toggleExclude = (id: string) => {
    const excluded = draft.excluded_atom_ids.includes(id)
    setDraft({ ...draft, excluded_atom_ids: excluded ? draft.excluded_atom_ids.filter((item) => item !== id) : [...draft.excluded_atom_ids, id], atom_ids: draft.atom_ids.filter((item) => item !== id) })
  }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4">
    <div className="flex max-h-[88vh] w-[min(980px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl">
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div><p className="text-sm font-semibold text-foreground">管理本章生成依据</p><p className="mt-1 text-xs text-muted-foreground">选择会保存到当前项目，后续重新打开本章仍会保留。</p></div>
        <button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭依据管理"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex gap-1 border-b border-border px-5 pt-3"><button className={cn("border-b-2 px-3 pb-2 text-xs", currentTab === "atoms" ? "border-primary text-primary" : "border-transparent text-muted-foreground")} onClick={() => setCurrentTab("atoms")}>优质原子</button><button className={cn("border-b-2 px-3 pb-2 text-xs", currentTab === "skills" ? "border-primary text-primary" : "border-transparent text-muted-foreground")} onClick={() => setCurrentTab("skills")}>写作技巧</button></div>
      <div className="min-h-0 flex-1 overflow-auto p-5">
        {currentTab === "atoms" ? <>
          <div className="flex flex-wrap gap-2"><div className="relative min-w-[220px] flex-1"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" /><TextInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索工艺、项目、章节标题或正文" className="pl-8" /></div><button type="button" onClick={() => setIndex("全部")} className={cn("rounded border px-3 py-2 text-xs", index === "全部" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground")}>全部</button>{processIndexes.map((item) => <button key={item} type="button" onClick={() => setIndex(item)} className={cn("max-w-[180px] truncate rounded border px-3 py-2 text-xs", index === item ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground")} title={item}>{item}</button>)}</div>
          <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground"><span>{loading ? "正在读取已发布原子..." : `索引结果 ${visibleAtoms.length} 条`}</span><span>已固定 {draft.atom_ids.length} 条 · 已排除 {draft.excluded_atom_ids.length} 条</span></div>
          <div className="mt-3 grid gap-2">{visibleAtoms.map((atom) => { const selected = draft.atom_ids.includes(atom.id); const excluded = draft.excluded_atom_ids.includes(atom.id); return <div key={atom.id} className={cn("flex items-start gap-3 rounded border px-3 py-2.5", selected ? "border-primary/50 bg-primary/[0.04]" : excluded ? "border-amber-300 bg-amber-50/50" : "border-border")}><button type="button" onClick={() => toggleAtom(atom.id)} className={cn("mt-0.5 h-4 w-4 shrink-0 rounded border text-[10px]", selected ? "border-primary bg-primary text-white" : "border-border")}>{selected ? "✓" : ""}</button><div className="min-w-0 flex-1"><p className="text-xs font-medium text-foreground">{atom.title_path.join(" / ") || "未命名原子"}</p><p className="mt-1 text-[11px] text-muted-foreground">{atom.process || "未标注工艺"} · {atom.project_name} · 质量 {(atom.quality_score * 100).toFixed(0)}%</p><p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-foreground/80">{atom.content}</p></div><button type="button" onClick={() => toggleExclude(atom.id)} className="shrink-0 text-[10px] text-muted-foreground hover:text-amber-700">{excluded ? "取消排除" : "排除"}</button></div> })}</div>
        </> : <>
          <p className="text-xs leading-relaxed text-muted-foreground">技巧只影响章节结构、工艺展开和表达方式，不会成为项目事实。可保留自动匹配结果，也可手动增删。</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">{skills.map((skill) => { const selected = draft.skill_keys.includes(skill); return <button key={skill} type="button" onClick={() => setDraft({ ...draft, skill_keys: selected ? draft.skill_keys.filter((item) => item !== skill) : [...draft.skill_keys, skill] })} className={cn("rounded border px-3 py-2 text-left text-xs", selected ? "border-primary bg-primary/[0.05] text-primary" : "border-border text-foreground")}>{selected ? "✓ " : "○ "}{skill}</button> })}</div>
          <div className="mt-3 flex gap-2"><TextInput value={customSkill} onChange={(event) => setCustomSkill(event.target.value)} placeholder="补充一个本章写作技巧，例如：先总述后分工序展开" className="flex-1" /><Button size="sm" variant="outline" onClick={() => { const value = customSkill.trim(); if (value && !draft.skill_keys.includes(value)) setDraft({ ...draft, skill_keys: [...draft.skill_keys, value] }); setCustomSkill("") }} icon={<Plus className="h-3.5 w-3.5" />}>添加</Button></div>
        </>}
        <label className="mt-5 block text-xs font-medium text-foreground">本章依据提示词 <span className="font-normal text-muted-foreground">（项目级保存，可随时修改）</span></label>
        <TextArea rows={4} value={draft.prompt} onChange={(event) => setDraft({ ...draft, prompt: event.target.value })} className="mt-2" placeholder="例如：重点展开雨季施工、通风排烟和质量检查闭环；不要套用参考项目参数。" />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3"><p className="text-[11px] text-muted-foreground">未选中的自动匹配仍可参与；排除项不会进入本章生成。</p><div className="flex gap-2"><Button size="sm" variant="outline" onClick={onClose}>取消</Button><Button size="sm" loading={saving} onClick={() => onSave(draft)} icon={<Save className="h-3.5 w-3.5" />}>保存本章依据</Button></div></div>
    </div>
  </div>
}

function BasisColumn({
  icon,
  title,
  role,
  count,
  lines,
  items,
  itemsOpen,
  onToggleItems,
  onOpenItem,
  itemLabel = "来源",
  loadingItemId,
  empty,
  actionLabel,
  onAction,
}: {
  icon: React.ReactNode
  title: string
  role: string
  count: number
  lines: string[]
  items?: Array<{ id: string; label: string; summary: string }>
  itemsOpen?: boolean
  onToggleItems?: () => void
  onOpenItem?: (item: { id: string; label: string; summary: string }) => void
  itemLabel?: string
  loadingItemId?: string | null
  empty: string
  actionLabel?: string
  onAction?: () => void
}) {
  return (
    <div className="min-w-0 px-5 py-4">
      <p className="flex items-center gap-2 text-xs font-semibold text-foreground">{icon}{title}<span className="text-muted-foreground">{count}</span></p>
      <div className="mt-1 flex items-start justify-between gap-2"><p className="min-w-0 text-[11px] leading-relaxed text-muted-foreground">{role}</p>{onAction ? <button type="button" onClick={onAction} className="shrink-0 rounded border border-primary/25 bg-primary/[0.04] px-2 py-1 text-[10px] font-semibold text-primary transition-colors hover:border-primary/50 hover:bg-primary/[0.09]">{actionLabel ?? "管理"}</button> : null}</div>
      {lines.length ? items?.length && onToggleItems && onOpenItem ? (
        <>
          <button type="button" onClick={onToggleItems} className="mt-2 flex items-center gap-1 text-[11px] font-medium text-primary hover:underline">
            {itemsOpen ? `收起${itemLabel}列表` : `点击查看 ${items.length} 项${itemLabel}`}
            <ChevronRight className={cn("h-3 w-3 transition-transform", itemsOpen && "rotate-90")} />
          </button>
          {itemsOpen ? <ul className="mt-2 max-h-56 space-y-1.5 overflow-y-auto pr-1">
            {items.map((item) => <li key={item.id} className="rounded border border-border bg-card px-2.5 py-2 hover:border-primary/40">
              <div className="flex items-start gap-2"><button type="button" onClick={() => onOpenItem(item)} disabled={Boolean(loadingItemId)} className="min-w-0 flex-1 text-left disabled:cursor-wait disabled:opacity-70">
                <span className="block text-[11px] font-medium leading-relaxed text-foreground">{item.label}</span>
                {item.summary ? <span className="mt-1 line-clamp-2 block text-[10px] leading-relaxed text-muted-foreground">{item.summary}</span> : null}
                <span className="mt-1 flex items-center gap-1 text-[10px] text-primary">{loadingItemId === item.id ? "正在读取..." : "点击查看具体内容"}<FileText className="h-3 w-3" /></span>
              </button></div>
            </li>)}
          </ul> : null}
        </>
      ) : <details className="mt-2"><summary className="cursor-pointer text-[11px] font-medium text-primary">查看 {lines.length} 项匹配依据</summary><ul className="mt-2 max-h-36 space-y-1 overflow-y-auto">{lines.map((line, index) => <li key={`${index}-${line}`} className="text-[11px] leading-relaxed text-foreground/80">{line}</li>)}</ul></details> : <p className="mt-2 text-[11px] text-muted-foreground">{empty}</p>}
    </div>
  )
}

function GenerationReceipt({ chapter }: { chapter: ChapterResponse }) {
  const metadata = chapter.generation_metadata ?? {}
  const units = Array.isArray(metadata.writing_units) ? metadata.writing_units as Array<Record<string, unknown>> : []
  const evidence = new Set<string>()
  const atoms = new Set<string>()
  const skills = new Set<string>()
  units.forEach((unit) => {
    ;(Array.isArray(unit.evidence_ids) ? unit.evidence_ids : []).forEach((item) => evidence.add(String(item)))
    ;(Array.isArray(unit.reference_atom_ids) ? unit.reference_atom_ids : []).forEach((item) => atoms.add(String(item)))
    ;(Array.isArray(unit.writing_skill_keys) ? unit.writing_skill_keys : []).forEach((item) => skills.add(String(item)))
  })
  return (
    <div className="border-y border-border bg-muted/25 px-5 py-3">
      <p className="text-xs font-semibold text-foreground">本版本生成凭据</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {units.length} 个写作单元 · {evidence.size} 条投标证据 · {atoms.size} 条参考原子 · {skills.size} 项写作技巧
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground">项目事实以投标证据为准；原子与技巧仅用于技术展开。所有编号随版本保留，可在来源映射中追溯。</p>
    </div>
  )
}

function generationQuality(metadata: Record<string, unknown> | undefined) {
  const review = metadata?.quality_review
  if (!review || typeof review !== "object") return null
  const value = review as Record<string, unknown>
  const messages = (items: unknown) => Array.isArray(items) ? items.map((item) => {
    if (item && typeof item === "object") {
      const record = item as Record<string, unknown>
      return String(record.message ?? record.code ?? "存在待复核问题")
    }
    return String(item)
  }) : []
  return {
    status: String(value.status ?? ""),
    issues: messages(value.issues),
    nextActions: messages(value.next_actions),
  }
}

function SourcePanel({ projectId, chapter, loading }: { projectId: string; chapter: ChapterResponse | null; loading: boolean }) {
  const mapping = chapter?.source_mapping
  const toast = useToast()
  const [section, setSection] = useState<SourceSection | null>(null)
  const [focusedEvidence, setFocusedEvidence] = useState<SourceEvidenceSpan | null>(null)
  const [loadingSectionId, setLoadingSectionId] = useState<string | null>(null)

  const openSection = async (sectionId: string, evidence?: SourceEvidenceSpan | null) => {
    setLoadingSectionId(sectionId)
    try {
      setSection(await getSourceSection(projectId, sectionId))
      setFocusedEvidence(evidence ?? null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "读取原文失败")
    } finally {
      setLoadingSectionId(null)
    }
  }

  return (
    <>
      <Card className="p-5">
        <SectionTitle title="来源映射" description="投标原文决定项目事实。先看匹配理由和关键证据，再点击打开全文核对。" />
        {loading ? (
          <LoadingBlock label="加载来源..." />
        ) : !mapping?.matches?.length ? (
          <p className="mt-3 text-xs text-muted-foreground">暂无来源映射。生成本章后会展示匹配章节与证据。</p>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span className="rounded-full bg-primary/10 px-2 py-1 text-primary">{mapping.matches.length} 个匹配章节</span>
              <span className="rounded-full bg-muted px-2 py-1">{mapping.evidence?.length ?? 0} 条关键证据</span>
              {mapping.missing_evidence?.length ? <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-800">待补 {mapping.missing_evidence.length} 项</span> : null}
            </div>
            <ul className="mt-3 grid gap-2 md:grid-cols-2">
              {mapping.matches.map((m) => {
                const evidence = (mapping.evidence ?? []).filter((item) => item.section_id === m.section_id).slice(0, 2)
                return (
                  <li key={`${m.section_id}-${m.usage}`} className="rounded-[var(--radius)] border border-border bg-muted/30 p-3">
                    <p className="truncate text-xs font-semibold text-foreground">{m.title_path.join(" / ")}</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{m.reason}</p>
                    <p className="mt-2 text-[11px] text-muted-foreground">{m.usage} · 匹配度 {(m.confidence * 100).toFixed(0)}%</p>
                    {evidence.length ? <div className="mt-2 space-y-1.5">
                      {evidence.map((item) => (
                        <button key={item.evidence_id} type="button" onClick={() => void openSection(m.section_id, item)} className="block w-full rounded border border-primary/15 bg-card px-2.5 py-2 text-left hover:border-primary/40">
                          <span className="line-clamp-2 text-[11px] leading-relaxed text-foreground">“{item.quote || item.summary || "已匹配证据，打开原文查看"}”</span>
                          <span className="mt-1 flex items-center gap-1 text-[10px] text-primary"><FileText className="h-3 w-3" />查看这条证据的原文</span>
                        </button>
                      ))}
                    </div> : null}
                    <div className="mt-2 flex items-center justify-between gap-2 border-t border-border/70 pt-2">
                      <p className="min-w-0 truncate text-[10px] text-muted-foreground">{m.section_id}</p>
                      <Button size="sm" variant="outline" loading={loadingSectionId === m.section_id} onClick={() => void openSection(m.section_id)} icon={<FileText className="h-3.5 w-3.5" />}>
                        打开全文
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </Card>
      {section ? <SourceSectionModal section={section} focusedEvidence={focusedEvidence} onClose={() => { setSection(null); setFocusedEvidence(null) }} /> : null}
    </>
  )
}

function SourceSectionModal({ section, focusedEvidence, onClose }: { section: SourceSection; focusedEvidence: SourceEvidenceSpan | null; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4">
      <div className="flex max-h-[86vh] w-[min(980px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{section.title_path.join(" / ")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {section.section_id} · {section.source_file}
            </p>
            {focusedEvidence ? <p className="mt-1 text-[11px] text-primary">映射证据 {focusedEvidence.evidence_id} · {focusedEvidence.start_line ? `原文第 ${focusedEvidence.start_line}-${focusedEvidence.end_line ?? focusedEvidence.start_line} 行` : "已定位到本节"}</p> : null}
          </div>
          <button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭原文查看">
            <X className="h-4 w-4" />
          </button>
        </div>
        {focusedEvidence ? <div className="border-b border-border bg-primary/[0.04] px-5 py-3">
          <p className="text-[11px] font-medium text-primary">本次匹配引用</p>
          <blockquote className="mt-1 border-l-2 border-primary/40 pl-3 text-xs leading-relaxed text-foreground">{focusedEvidence.quote || focusedEvidence.summary || "暂无可显示的引用句"}</blockquote>
          {focusedEvidence.matched_terms?.length ? <p className="mt-1 text-[10px] text-muted-foreground">匹配词：{focusedEvidence.matched_terms.join("、")}</p> : null}
        </div> : null}
        <pre className="flex-1 overflow-auto whitespace-pre-wrap break-words p-5 font-mono text-[13px] leading-relaxed text-foreground">{section.content}</pre>
      </div>
    </div>
  )
}

function ChapterEditor({
  projectId,
  nodeId,
  nodeTitle,
  chapter,
  onChanged,
}: {
  projectId: string
  nodeId: string
  nodeTitle: string
  chapter: ChapterResponse | null
  onChanged: () => void
}) {
  const toast = useToast()
  const [mode, setMode] = useState<"markdown" | "preview" | "evidence" | "edit">("markdown")
  const [draft, setDraft] = useState(cleanChapterMarkdown(chapter?.markdown ?? ""))
  const [saving, setSaving] = useState(false)
  const [confirmingReview, setConfirmingReview] = useState(false)
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const mdEditorRef = useRef<MdEditor>(null)
  const quality = generationQuality(chapter?.generation_metadata)

  const insertMarkdown = (prefix: string, suffix = "", placeholder = "文本") => {
    const editor = editorRef.current
    if (!editor) return
    const start = editor.selectionStart
    const end = editor.selectionEnd
    const selected = draft.slice(start, end) || placeholder
    const next = `${draft.slice(0, start)}${prefix}${selected}${suffix}${draft.slice(end)}`
    setDraft(next)
    requestAnimationFrame(() => {
      editor.focus()
      const cursor = start + prefix.length + selected.length + suffix.length
      editor.setSelectionRange(cursor, cursor)
    })
  }

  const confirmReview = async () => {
    if (!chapter?.version?.id) return
    setConfirmingReview(true)
    try {
      await confirmVersionReview(projectId, nodeId, chapter.version.id)
      toast.success("已确认当前修订版本可用")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "确认失败")
    } finally {
      setConfirmingReview(false)
    }
  }

  const saveManual = async () => {
    if (!draft.trim()) {
      toast.error("正文不能为空")
      return
    }
    setSaving(true)
    try {
      await createManualVersion(projectId, nodeId, `${nodeTitle}（人工编辑）`, draft, true)
      toast.success("已保存为新版本并选用")
      setMode("markdown")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const jumpPreviewToEditor = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!draft) return
    const target = event.target as HTMLElement
    const visibleText = target.textContent?.trim()
    if (!visibleText) return
    const source = cleanChapterMarkdown(draft)
    const located = locateMarkdownText(source, visibleText)
    setMode("markdown")
    requestAnimationFrame(() => {
      const editor = mdEditorRef.current?.getMdElement() ?? editorRef.current
      if (!editor) return
      editor.focus()
      const position = located?.start ?? 0
      const end = located?.end ?? Math.min(source.length, position + Math.min(visibleText.length, 80))
      if (mdEditorRef.current) mdEditorRef.current.setSelection({ start: position, end })
      else editor.setSelectionRange(position, end)
      editor.scrollTop = Math.max(0, position / Math.max(1, source.length) * editor.scrollHeight - editor.clientHeight * 0.35)
    })
  }

  useEffect(() => {
    if (mode !== "markdown") return
    const html = mdEditorRef.current?.getHtmlElement()
    const editor = mdEditorRef.current?.getMdElement()
    if (!html || !editor) return
    editor.setAttribute("aria-label", "Markdown 正文编辑区")
    const handlePreviewClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      const visibleText = target.textContent?.trim()
      if (!visibleText) return
      const source = cleanChapterMarkdown(draft)
      const located = locateMarkdownText(source, visibleText)
      if (!located) return
      mdEditorRef.current?.setSelection(located)
      mdEditorRef.current?.getMdElement()?.focus()
    }
    html.addEventListener("click", handlePreviewClick)
    return () => html.removeEventListener("click", handlePreviewClick)
  }, [draft, mode])

  if (!chapter?.markdown?.trim()) {
    return (
      <Card className="p-5">
        <EmptyState icon={<FileEdit className="h-7 w-7" />} title="本章节暂无正文" description="点击“生成本章”，系统会依据来源章节、目录四模块和人工补充生成新版本。" />
      </Card>
    )
  }

  return (
    <Card className="flex flex-col p-5">
      {quality && quality.status !== "passed" ? (
        <div className="mb-4 rounded-[var(--radius)] border border-amber-300 bg-amber-50 px-3.5 py-3 text-amber-950">
          <p className="flex items-center gap-2 text-xs font-semibold"><AlertTriangle className="h-4 w-4" />当前选用版本仍需复核</p>
          <p className="mt-1 text-[11px] leading-relaxed">{quality.issues[0] ?? "本版本尚未通过完整审查，请核对正文和生成凭据。"}</p>
          {quality.nextActions[0] ? <p className="mt-1 text-[11px] leading-relaxed text-amber-800">建议：{quality.nextActions[0]}</p> : null}
          {chapter?.version?.source_type === "ai_edit" ? <div className="mt-2">
            <Button size="sm" variant="outline" loading={confirmingReview} onClick={confirmReview} icon={<CheckCircle2 className="h-3.5 w-3.5" />}>
              我已复核，确认可用
            </Button>
          </div> : null}
        </div>
      ) : null}
      <div className="flex items-center justify-between gap-3">
        <SectionTitle title="章节正文" />
        <div className="flex items-center gap-1 rounded-[var(--radius)] border border-border p-0.5">
          <TabBtn active={mode === "markdown"} onClick={() => { setDraft(cleanChapterMarkdown(chapter.markdown)); setMode("markdown") }}>
            Markdown 正文
          </TabBtn>
          <TabBtn active={mode === "preview"} onClick={() => setMode("preview")}>
            渲染预览
          </TabBtn>
          <TabBtn active={mode === "evidence"} onClick={() => setMode("evidence")}>生成凭据</TabBtn>
          <TabBtn
            active={mode === "edit"}
            onClick={() => {
              setDraft(cleanChapterMarkdown(chapter.markdown))
              setMode("edit")
            }}
          >
            编辑 Markdown
          </TabBtn>
        </div>
      </div>
      <div className="mt-4">
        {mode === "markdown" ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3 rounded-[var(--radius)] border border-primary/20 bg-primary/[0.04] px-3 py-2">
              <p className="text-[11px] text-muted-foreground">成熟 Markdown 编辑器：左侧编辑、右侧预览，支持工具栏和同步滚动。</p>
              <Button size="sm" onClick={saveManual} loading={saving} icon={<Save className="h-3.5 w-3.5" />}>保存新版本</Button>
            </div>
            <div className="overflow-hidden rounded-[var(--radius)] border border-border bg-card [&_.rc-md-editor]:!border-0 [&_.rc-md-editor]:!bg-card [&_.rc-md-editor_.rc-md-navigation]:!bg-muted/30 [&_.rc-md-editor_.sec-md_.input]:!bg-background/40 [&_.rc-md-editor_.sec-html]:!bg-card">
              <MdEditor
                ref={mdEditorRef}
                value={draft}
                style={{ height: "min(62vh, 760px)" }}
                renderHTML={(text) => new MarkdownIt({ html: true, breaks: true, linkify: true }).render(text)}
                onChange={({ text }) => setDraft(text)}
                config={{ view: { menu: true, md: true, html: true }, canView: { menu: true, md: true, html: true } }}
                placeholder="在这里编辑章节 Markdown 正文..."
              />
            </div>
          </div>
        ) : mode === "preview" ? (
          <div className="relative max-h-[62vh] overflow-y-auto rounded-[var(--radius)] border border-border bg-background/40 p-5">
            <div className="absolute right-3 top-3 z-10">
              <Button size="sm" variant="outline" onClick={() => { setDraft(cleanChapterMarkdown(chapter.markdown)); setMode("markdown") }} icon={<Pencil className="h-3.5 w-3.5" />}>
                直接编辑
              </Button>
            </div>
            <Markdown content={cleanChapterMarkdown(chapter.markdown)} className="cursor-text" onClick={jumpPreviewToEditor} />
          </div>
        ) : mode === "evidence" ? (
          <div className="rounded-[var(--radius)] border border-border bg-muted/20 p-4"><GenerationReceipt chapter={chapter} /></div>
        ) : (
          <div className="flex flex-col gap-3">
            <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} className="min-h-[52vh] font-mono text-[13px] leading-relaxed" />
            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setMode("markdown")}>
                取消
              </Button>
              <Button size="sm" onClick={saveManual} loading={saving} icon={<Save className="h-4 w-4" />}>
                保存为新版本
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function MarkdownTool({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="inline-flex h-7 min-w-7 items-center justify-center rounded border border-transparent px-1.5 text-xs font-medium text-muted-foreground hover:border-border hover:bg-card hover:text-foreground"
    >
      {children}
    </button>
  )
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cn("inline-flex items-center gap-1.5 rounded-[calc(var(--radius)-2px)] px-2.5 py-1 text-xs font-medium transition-colors", active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>
      {children}
    </button>
  )
}

function cleanChapterMarkdown(markdown: string): string {
  const raw = markdown || ""
  const rawLines = raw.split(/\r?\n/)
  const bodyStart = rawLines.findIndex((line) => /^##\s+生成正文\s*$/.test(line.trim()))
  const contentLines = bodyStart >= 0 ? rawLines.slice(bodyStart + 1) : rawLines
  const nextSection = contentLines.findIndex((line) => /^##\s+/.test(line.trim()))
  const lines = nextSection >= 0 ? contentLines.slice(0, nextSection) : contentLines
  const output: string[] = []
  for (const line of lines) {
    if (/^#{1,2}\s+(?:主要来源摘要|人工补充需补充|特殊备注)\s*$/i.test(line.trim())) continue
    if (/^#\s+/.test(line.trim())) continue
    const withoutTrace = line
      .replace(/\s*(?:[（(][^()（）]*\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=][^()（）]*[）)]|\[[^\[\]]*\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=][^\[\]]*\])/gi, "")
      .replace(/\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=]\s*[^\s，。；;,]+/gi, "")
    const cleaned = withoutTrace.replace(/【需人工补充：[^】]+】/g, "").replace(/\s{2,}/g, " ").trimEnd()
    if (/^\s*[-*]\s*[。；;，,：:]?\s*$/.test(cleaned)) continue
    if (cleaned.trim()) output.push(cleaned)
  }
  return output.join("\n").trim()
}

function locateMarkdownText(markdown: string, renderedText: string): { start: number; end: number } | null {
  const target = renderedText.replace(/\s+/g, " ").trim().slice(0, 80)
  if (!target) return null
  const direct = markdown.indexOf(target)
  if (direct >= 0) return { start: direct, end: direct + target.length }
  const compactTarget = target.replace(/\s+/g, "").replace(/[*_`]/g, "")
  let offset = 0
  for (const line of markdown.split("\n")) {
    const compactLineChars: string[] = []
    const rawIndexes: number[] = []
    const headingPrefix = line.match(/^\s{0,3}#{1,6}\s*/)?.[0].length ?? 0
    for (let index = headingPrefix; index < line.length; index += 1) {
      const char = line[index]
      if (/[*_`]/.test(char)) continue
      if (/\s/.test(char)) continue
      compactLineChars.push(char)
      rawIndexes.push(index)
    }
    const compactLine = compactLineChars.join("")
    const targetPart = compactTarget.slice(0, 40)
    const matchIndex = compactLine.indexOf(targetPart)
    if (matchIndex >= 0 && rawIndexes[matchIndex] !== undefined) {
      const endIndex = Math.min(rawIndexes.length - 1, matchIndex + targetPart.length - 1)
      return { start: offset + rawIndexes[matchIndex], end: offset + rawIndexes[endIndex] + 1 }
    }
    offset += line.length + 1
  }
  return null
}

function VersionPanel({
  versions,
  loading,
  selectedId,
  onReview,
}: {
  versions: ChapterVersion[]
  loading: boolean
  selectedId: string | null
  onReview: (version: ChapterVersion) => void
}) {
  return (
    <Card className="p-4">
      <SectionTitle title="版本历史" right={<History className="h-4 w-4 text-muted-foreground" />} />
      <div className="mt-3">
        {loading ? (
          <LoadingBlock label="加载版本..." />
        ) : !versions.length ? (
          <p className="py-4 text-center text-xs text-muted-foreground">暂无历史版本</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {versions.map((v) => {
              const isSelected = v.id === selectedId
              const quality = generationQuality(v.generation_metadata)
              return (
                <li key={v.id} className={cn("rounded-[var(--radius)] border p-2.5", isSelected ? "border-accent/40 bg-accent/[0.05]" : "border-border")}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground">v{v.version_no}</span>
                      <StatusBadge status={v.status} />
                    </div>
                    {isSelected ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        选用
                      </span>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => onReview(v)}>
                        查看并比较
                      </Button>
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {v.source_type} · {formatDateTime(v.created_at)}
                  </p>
                  {quality ? <p className={cn("mt-1 text-[10px]", quality.status === "passed" ? "text-[var(--color-success)]" : "text-[var(--color-warning)]")}>
                    {quality.status === "passed" ? "内容审查通过" : `内容待复核${quality.issues.length ? ` · ${quality.issues[0]}` : ""}`}
                  </p> : <p className="mt-1 text-[10px] text-muted-foreground">无审查凭据</p>}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Card>
  )
}

function VersionCompareDrawer({
  projectId,
  nodeId,
  current,
  candidate,
  onClose,
  onSelected,
}: {
  projectId: string
  nodeId: string
  current: ChapterVersion | null
  candidate: ChapterVersion
  onClose: () => void
  onSelected: () => Promise<void>
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const adopt = async () => {
    setBusy(true)
    try {
      await selectVersion(projectId, nodeId, candidate.id)
      toast.success(`已采用 v${candidate.version_no}，当前正文已更新`)
      await onSelected()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "采用版本失败")
    } finally {
      setBusy(false)
    }
  }
  return (
    <WorkspaceDrawer title="确认章节新版本" onClose={onClose}>
      <div className="flex h-full flex-col gap-4">
        <div className="rounded-[var(--radius)] border border-primary/20 bg-primary/[0.04] px-3 py-2 text-xs leading-relaxed text-muted-foreground">
          新生成内容已保存为候选版本，尚未覆盖当前正文。请比较两版后再决定是否采用。
        </div>
        <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-2">
          <VersionComparePane title={current ? `当前选用 v${current.version_no}` : "当前正文"} version={current} />
          <VersionComparePane title={`新候选 v${candidate.version_no}`} version={candidate} highlighted />
        </div>
        <div className="flex shrink-0 justify-end gap-2 border-t border-border pt-3">
          <Button variant="outline" onClick={onClose}>暂不采用</Button>
          <Button variant="accent" onClick={adopt} loading={busy} icon={<CheckCircle2 className="h-4 w-4" />}>采用新版本</Button>
        </div>
      </div>
    </WorkspaceDrawer>
  )
}

function VersionComparePane({ title, version, highlighted = false }: { title: string; version: ChapterVersion | null; highlighted?: boolean }) {
  return (
    <section className={cn("flex min-h-0 flex-col overflow-hidden rounded-[var(--radius)] border", highlighted ? "border-accent/40 bg-accent/[0.025]" : "border-border bg-background/30")}>
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-xs font-semibold text-foreground">{title}</span>
        <span className="text-[10px] text-muted-foreground">{version ? `${version.source_type} · ${formatDateTime(version.created_at)}` : "暂无已选版本"}</span>
      </div>
      <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-[12px] leading-relaxed text-foreground">{version ? cleanChapterMarkdown(version.markdown) : "当前尚无可比较的正文。"}</pre>
    </section>
  )
}

function AIEditPanel({
  projectId,
  nodeId,
  onApplied,
}: {
  projectId: string
  nodeId: string
  onApplied: () => void
}) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const [suggestion, setSuggestion] = useState("")
  const [proposalId, setProposalId] = useState<string | null>(null)
  const [preview, setPreview] = useState("")
  const [applying, setApplying] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  const editJob = activeJob?.job_type === "chapter_edit_proposal" && String(activeJob.payload.node_id ?? "") === nodeId ? activeJob : null

  const loadPendingProposal = async () => {
    try {
      const items = await listChapterProposals(projectId, nodeId)
      const result = items[0]
      if (!result) return
      setProposalId(result.id)
      setPreview(cleanChapterMarkdown(typeof result.preview?.display_markdown === "string" ? result.preview.display_markdown as string : String(result.preview?.markdown ?? "")))
    } catch {
      // A missing proposal is a normal empty state.
    }
  }

  useEffect(() => {
    void loadPendingProposal()
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === projectId && job?.job_type === "chapter_edit_proposal" && String(job?.payload?.node_id ?? "") === nodeId) void loadPendingProposal()
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [nodeId, projectId])

  const propose = async () => {
    if (!suggestion.trim()) {
      toast.error("请描述修改要求")
      return
    }
    setProposalId(null)
    try {
      await startJob("chapter_edit_proposal", { node_id: nodeId, suggestion: suggestion.trim() })
      toast.success("正文修改已在后台开始，可继续浏览其他章节")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    }
  }

  const apply = async () => {
    if (!proposalId) return
    setApplying(true)
    try {
      await applyChapterProposal(projectId, nodeId, proposalId)
      toast.success("修改建议已应用为新版本，请完成内容复核")
      setProposalId(null)
      setSuggestion("")
      setPreview("")
      onApplied()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "应用失败")
    } finally {
      setApplying(false)
    }
  }

  const reject = async () => {
    if (!proposalId) return
    setRejecting(true)
    try {
      await rejectChapterProposal(projectId, nodeId, proposalId)
      toast.success("已忽略该修改建议")
      setProposalId(null)
      setPreview("")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "忽略建议失败")
    } finally {
      setRejecting(false)
    }
  }

  return (
    <Card className="p-5">
      <SectionTitle title="AI 修改建议" description="修改建议先预览，不会直接覆盖当前正文；确认后保存为新版本。" />
      <div className="mt-4 flex flex-col gap-3">
        <TextArea rows={3} value={suggestion} onChange={(e) => setSuggestion(e.target.value)} placeholder="例如：在已确认提纲范围内，补充季节变化对施工安排的影响；没有来源支持的数值保留待补标记。" />
        <Button variant="accent" onClick={propose} loading={Boolean(editJob)} icon={<Sparkles className="h-4 w-4" />}>
          生成修改建议
        </Button>
        {editJob ? <p className="text-[11px] text-primary">{editJob.message}。本次只修改生成正文，不会改动来源摘要和人工补充项。</p> : null}
        {proposalId ? (
          <div className="rounded-[var(--radius)] border border-accent/30 bg-accent/[0.04] p-3">
            <p className="mb-2 text-xs font-medium text-accent">修改预览</p>
            <div className="max-h-56 overflow-y-auto rounded border border-border bg-card p-3">
              <Markdown content={preview} />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button size="sm" variant="outline" onClick={reject} loading={rejecting}>
                忽略建议
              </Button>
              <Button size="sm" onClick={apply} loading={applying} icon={<Pencil className="h-4 w-4" />}>
                应用并进入复核
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  )
}
