import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, ArrowLeft, ArrowRight, BookOpenCheck, BrainCircuit, CheckCircle2, ChevronRight, Database, FileEdit, FileText, GitBranch, History, Layers3, Pencil, Save, Sparkles, Wand2, X } from "lucide-react"
import {
  applyChapterProposal,
  createManualVersion,
  getChapterGenerationPreflight,
  generateChapterWritingSkill,
  getChapter,
  getSourceSection,
  listReferenceAtoms,
  listOutlineNodes,
  listChapterTasks,
  listVersions,
  proposeChapterEdit,
  rejectChapterProposal,
  selectVersion,
  type ChapterResponse,
  type ChapterGenerationPreflight,
  type SourceSection,
  type SourceEvidenceSpan,
  type ReferenceAtomDetail,
  type ChapterVersion,
  type ChapterTaskSummary,
  type OutlineNode,
  type ProjectResponse,
} from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, LoadingBlock, SectionTitle, StatusBadge, TextArea } from "@/components/ui"
import { Markdown } from "@/components/Markdown"
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
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <Card className="flex max-h-[calc(100vh-140px)] flex-col p-4 lg:sticky lg:top-20">
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
  const activeIndex = nodes.findIndex((item) => item.node_id === node.node_id)
  const currentJob = activeJob && String(activeJob.payload.node_id ?? "") === node.node_id ? activeJob : null

  const reloadAll = () => Promise.all([chapter.reload(), versionsData.reload()])

  const handleGenerate = async () => {
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
      if (job?.project_id === projectId && String(job?.payload?.node_id ?? "") === node.node_id) void Promise.all([reloadAll(), preflight.reload()])
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
            <Button variant="outline" onClick={handleGenerateChildren} loading={generatingChildren} icon={<GitBranch className="h-4 w-4" />}>
              生成子章节
            </Button>
            <Button onClick={handleGenerate} loading={generating || Boolean(currentJob)} disabled={Boolean(activeJob && !currentJob)} icon={<Wand2 className="h-4 w-4" />}>
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

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <div className="flex min-w-0 flex-col gap-5">
          <GenerationBasisPanel projectId={projectId} preflight={preflight.data} loading={preflight.loading} />
          <SourcePanel projectId={projectId} chapter={chapter.data} loading={chapter.loading} />
          {chapter.loading ? (
            <Card className="p-5">
              <LoadingBlock label="加载章节内容..." />
            </Card>
          ) : (
            <ChapterEditor projectId={projectId} nodeId={node.node_id} nodeTitle={node.title} chapter={chapter.data} onChanged={reloadAll} />
          )}
          <AIEditPanel projectId={projectId} nodeId={node.node_id} baseMarkdown={chapter.data?.markdown ?? ""} onApplied={reloadAll} />
        </div>

        <div className="flex flex-col gap-5">
          <VersionPanel
            projectId={projectId}
            nodeId={node.node_id}
            versions={versionsData.data ?? []}
            loading={versionsData.loading}
            selectedId={chapter.data?.version?.id ?? null}
            onSelected={reloadAll}
          />
          <AttachmentPanel projectId={projectId} nodeId={node.node_id} />
        </div>
      </div>
    </div>
  )
}

function GenerationBasisPanel({ projectId, preflight, loading }: { projectId: string; preflight: ChapterGenerationPreflight | null; loading: boolean }) {
  const toast = useToast()
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const [sourceSection, setSourceSection] = useState<SourceSection | null>(null)
  const [atom, setAtom] = useState<ReferenceAtomDetail | null>(null)
  const [skill, setSkill] = useState<{ title: string; content: string[] } | null>(null)
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null)
  const [chapterSkill, setChapterSkill] = useState<Record<string, unknown> | null>(preflight?.chapter_writing_skill ?? null)
  const [skillLoading, setSkillLoading] = useState(false)

  useEffect(() => setChapterSkill(preflight?.chapter_writing_skill ?? null), [preflight?.chapter_writing_skill])

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

  if (loading) {
    return (
      <Card className="p-5">
        <LoadingBlock label="正在准备本章生成依据..." />
      </Card>
    )
  }
  if (!preflight) return null
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <p className="text-sm font-semibold text-foreground">生成前依据预览</p>
          <p className="mt-1 text-xs text-muted-foreground">{preflight.readiness.message}</p>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium", preflight.readiness.can_generate ? "bg-[color-mix(in_srgb,var(--color-success)_14%,transparent)] text-[var(--color-success)]" : "bg-[color-mix(in_srgb,var(--color-warning)_16%,transparent)] text-[var(--color-warning)]")}>
          {preflight.readiness.can_generate ? "依据已就绪" : "建议先补来源"}
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
          loadingItemId={loadingDetailId}
          empty="本章不强行使用原子"
        />
        <BasisColumn
          icon={<BrainCircuit className="h-4 w-4" />}
          title="写作技巧"
          role="控制结构与表达，不提供事实"
          count={preflight.writing_skill.matched_skill_keys.length || 1}
          lines={preflight.writing_skill.structure}
          items={preflight.writing_skill.matched_skill_keys.map((key) => ({ id: key, label: key, summary: preflight.writing_skill.structure.join("；") }))}
          itemsOpen={openGroup === "skill"}
          onToggleItems={() => setOpenGroup((value) => value === "skill" ? null : "skill")}
          onOpenItem={(item) => { setSkill({ title: item.label, content: preflight.writing_skill.structure }); setOpenGroup("skill") }}
          empty="使用通用章节组织规则"
        />
      </div>
      <div className="border-t border-border px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-foreground">章节专属 AI Writing Skill</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">根据项目概况、全局重点和本章来源生成的写作指挥规则，用于控制要点覆盖、组织顺序和事实边界。</p>
          </div>
          <Button size="sm" variant="outline" onClick={() => void generateSkill()} loading={skillLoading} icon={<Sparkles className="h-3.5 w-3.5" />}>
            {chapterSkill ? "刷新章节 Skill" : "生成章节 Skill"}
          </Button>
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
      {skill ? <BasisDetailModal title={skill.title} subtitle="写作技巧 · 仅用于章节结构与表达" content={skill.content.join("\n")} meta="写作规则不提供项目事实" onClose={() => setSkill(null)} /> : null}
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

function BasisDetailModal({ title, subtitle, meta, content, onClose }: { title: string; subtitle: string; meta: string; content: string; onClose: () => void }) {
  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4">
    <div className="flex max-h-[86vh] w-[min(900px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl">
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div className="min-w-0"><p className="truncate text-sm font-semibold text-foreground">{title}</p><p className="mt-1 text-xs text-muted-foreground">{subtitle}</p><p className="mt-1 text-[10px] text-primary">{meta}</p></div>
        <button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭依据详情"><X className="h-4 w-4" /></button>
      </div>
      <pre className="flex-1 overflow-auto whitespace-pre-wrap break-words p-5 text-[13px] leading-relaxed text-foreground">{content || "暂无可显示内容"}</pre>
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
  loadingItemId,
  empty,
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
  loadingItemId?: string | null
  empty: string
}) {
  return (
    <div className="min-w-0 px-5 py-4">
      <p className="flex items-center gap-2 text-xs font-semibold text-foreground">{icon}{title}<span className="text-muted-foreground">{count}</span></p>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{role}</p>
      {lines.length ? items?.length && onToggleItems && onOpenItem ? (
        <>
          <button type="button" onClick={onToggleItems} className="mt-2 flex items-center gap-1 text-[11px] font-medium text-primary hover:underline">
            {itemsOpen ? "收起来源列表" : `点击查看 ${items.length} 项来源`}
            <ChevronRight className={cn("h-3 w-3 transition-transform", itemsOpen && "rotate-90")} />
          </button>
          {itemsOpen ? <ul className="mt-2 max-h-56 space-y-1.5 overflow-y-auto pr-1">
            {items.map((item) => <li key={item.id}>
              <button type="button" onClick={() => onOpenItem(item)} disabled={Boolean(loadingItemId)} className="w-full rounded border border-border bg-card px-2.5 py-2 text-left hover:border-primary/40 disabled:cursor-wait disabled:opacity-70">
                <span className="block text-[11px] font-medium leading-relaxed text-foreground">{item.label}</span>
                {item.summary ? <span className="mt-1 line-clamp-2 block text-[10px] leading-relaxed text-muted-foreground">{item.summary}</span> : null}
                <span className="mt-1 flex items-center gap-1 text-[10px] text-primary">{loadingItemId === item.id ? "正在读取..." : "点击查看具体内容"}<FileText className="h-3 w-3" /></span>
              </button>
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
  const [mode, setMode] = useState<"preview" | "evidence" | "edit">("preview")
  const [draft, setDraft] = useState(cleanChapterMarkdown(chapter?.markdown ?? ""))
  const [saving, setSaving] = useState(false)

  const saveManual = async () => {
    if (!draft.trim()) {
      toast.error("正文不能为空")
      return
    }
    setSaving(true)
    try {
      await createManualVersion(projectId, nodeId, `${nodeTitle}（人工编辑）`, draft, true)
      toast.success("已保存为新版本并选用")
      setMode("preview")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  if (!chapter?.markdown?.trim()) {
    return (
      <Card className="p-5">
        <EmptyState icon={<FileEdit className="h-7 w-7" />} title="本章节暂无正文" description="点击“生成本章”，系统会依据来源章节、目录四模块和人工补充生成新版本。" />
      </Card>
    )
  }

  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-center justify-between gap-3">
        <SectionTitle title="章节正文" />
        <div className="flex items-center gap-1 rounded-[var(--radius)] border border-border p-0.5">
          <TabBtn active={mode === "preview"} onClick={() => setMode("preview")}>
            正文
          </TabBtn>
          <TabBtn active={mode === "evidence"} onClick={() => setMode("evidence")}>生成凭据</TabBtn>
          <TabBtn
            active={mode === "edit"}
            onClick={() => {
              setDraft(cleanChapterMarkdown(chapter.markdown))
              setMode("edit")
            }}
          >
            编辑
          </TabBtn>
        </div>
      </div>
      <div className="mt-4">
        {mode === "preview" ? (
          <div className="max-h-[62vh] overflow-y-auto rounded-[var(--radius)] border border-border bg-background/40 p-5">
            <Markdown content={cleanChapterMarkdown(chapter.markdown)} />
          </div>
        ) : mode === "evidence" ? (
          <div className="rounded-[var(--radius)] border border-border bg-muted/20 p-4"><GenerationReceipt chapter={chapter} /></div>
        ) : (
          <div className="flex flex-col gap-3">
            <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} className="min-h-[52vh] font-mono text-[13px] leading-relaxed" />
            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setMode("preview")}>
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

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={cn("inline-flex items-center gap-1.5 rounded-[calc(var(--radius)-2px)] px-2.5 py-1 text-xs font-medium transition-colors", active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>
      {children}
    </button>
  )
}

function cleanChapterMarkdown(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  const output: string[] = []
  let skippingLevel = 0
  for (const line of lines) {
    const heading = /^(#{1,6})\s+(.+)$/.exec(line.trim())
    if (heading && heading[2].includes("主要来源摘要")) {
      skippingLevel = heading[1].length
      continue
    }
    if (skippingLevel) {
      if (!heading || heading[1].length > skippingLevel) continue
      skippingLevel = 0
    }
    output.push(line)
  }
  return output.join("\n").trim()
}

function VersionPanel({
  projectId,
  nodeId,
  versions,
  loading,
  selectedId,
  onSelected,
}: {
  projectId: string
  nodeId: string
  versions: ChapterVersion[]
  loading: boolean
  selectedId: string | null
  onSelected: () => void
}) {
  const toast = useToast()
  const [busyId, setBusyId] = useState<string | null>(null)

  const select = async (versionId: string) => {
    setBusyId(versionId)
    try {
      await selectVersion(projectId, nodeId, versionId)
      toast.success("已切换选用版本")
      onSelected()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "切换失败")
    } finally {
      setBusyId(null)
    }
  }

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
                      <Button size="sm" variant="ghost" loading={busyId === v.id} onClick={() => select(v.id)}>
                        选用
                      </Button>
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {v.source_type} · {formatDateTime(v.created_at)}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Card>
  )
}

function AIEditPanel({
  projectId,
  nodeId,
  baseMarkdown,
  onApplied,
}: {
  projectId: string
  nodeId: string
  baseMarkdown: string
  onApplied: () => void
}) {
  const toast = useToast()
  const [suggestion, setSuggestion] = useState("")
  const [loading, setLoading] = useState(false)
  const [proposalId, setProposalId] = useState<string | null>(null)
  const [preview, setPreview] = useState("")
  const [applying, setApplying] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  const propose = async () => {
    if (!suggestion.trim()) {
      toast.error("请描述修改要求")
      return
    }
    setLoading(true)
    setProposalId(null)
    try {
      const result = await proposeChapterEdit(projectId, nodeId, suggestion.trim(), baseMarkdown)
      setProposalId(result.id)
      setPreview(typeof result.preview?.markdown === "string" ? (result.preview.markdown as string) : JSON.stringify(result.preview, null, 2))
      toast.success("已生成修改建议")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    } finally {
      setLoading(false)
    }
  }

  const apply = async () => {
    if (!proposalId) return
    setApplying(true)
    try {
      await applyChapterProposal(projectId, nodeId, proposalId)
      toast.success("修改建议已应用为新版本")
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
        <TextArea rows={3} value={suggestion} onChange={(e) => setSuggestion(e.target.value)} placeholder="例如：补充安全管理措施，压缩空泛表述，增加来源事实。" />
        <Button variant="accent" onClick={propose} loading={loading} icon={<Sparkles className="h-4 w-4" />}>
          生成修改建议
        </Button>
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
                确认并应用
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  )
}
