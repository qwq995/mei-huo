import { useEffect, useMemo, useState, type ReactNode } from "react"
import { ArrowDown, ArrowRight, ArrowUp, Calculator, ChevronRight, CornerDownLeft, CornerUpLeft, Download, ListTree, Pencil, Plus, RefreshCw, RotateCcw, Save, Search, Sparkles, Trash2, Wand2, X } from "lucide-react"
import {
  applyOutlineProposal,
  createOutlineNode,
  deleteOutlineNode,
  estimateOutlineWordCounts,
  getOutlineOverview,
  listOutlineNodes,
  listOutlineProposals,
  rejectOutlineProposal,
  restoreOutlineSnapshot,
  moveOutlineNode,
  updateOutlineNode,
  type AIProposal,
  type OutlineNode,
  type ProjectResponse,
} from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Badge, Button, Card, ConfirmDialog, EmptyState, LoadingBlock, SectionTitle, TextArea, TextInput } from "@/components/ui"
import { cn } from "@/lib/utils"
import { useJobs } from "@/components/Jobs"

type TreeNode = OutlineNode & { _children: TreeNode[] }
type RefineMode = "balanced" | "conservative" | "aggressive"
type NodeAction = { kind: "edit" | "children" | "delete"; node: OutlineNode }

function buildTree(nodes: OutlineNode[]): TreeNode[] {
  const map = new Map<string, TreeNode>()
  nodes.forEach((n) => map.set(n.node_id, { ...n, _children: [] }))
  const roots: TreeNode[] = []
  map.forEach((node) => {
    const parent = node.parent_id ? map.get(node.parent_id) : undefined
    if (parent) parent._children.push(node)
    else roots.push(node)
  })
  const sortRec = (list: TreeNode[]) => {
    list.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    list.forEach((n) => sortRec(n._children))
  }
  sortRec(roots)
  return roots
}

function filterTree(nodes: TreeNode[], query: string, enabledOnly: boolean, sourceOnly: boolean, missingOnly: boolean): TreeNode[] {
  const needle = query.trim().toLowerCase()
  return nodes.flatMap((node) => {
    const children = filterTree(node._children, query, enabledOnly, sourceOnly, missingOnly)
    const text = `${node.title} ${node.chapter_summary?.generated_overview ?? node.chapter_summary?.overview ?? ""}`.toLowerCase()
    const hasMissing = Boolean(node.chapter_summary?.missing_information?.length || node.chapter_summary?.unresolved_items?.length || node.manual_fill?.length)
    const matches = (!needle || text.includes(needle)) && (!enabledOnly || node.enabled !== false) && (!sourceOnly || Boolean(node.source_rules?.length)) && (!missingOnly || hasMissing)
    return matches || children.length ? [{ ...node, _children: children }] : []
  })
}

function countTreeNodes(nodes: TreeNode[]): number {
  return nodes.reduce((count, node) => count + 1 + countTreeNodes(node._children), 0)
}

function firstLeafNode(nodes: OutlineNode[]): OutlineNode | undefined {
  const parentIds = new Set(nodes.map((node) => node.parent_id).filter(Boolean))
  return nodes.find((node) => node.enabled !== false && !parentIds.has(node.node_id))
}

function splitLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
}

function joinLines(value?: string[]): string {
  return (value ?? []).join("\n")
}

export function OutlineStep({ project, onNext }: { project: ProjectResponse; onNext: () => void }) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const outline = useAsyncData<OutlineNode[]>(() => listOutlineNodes(project.project_id), [project.project_id])
  const [generating, setGenerating] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editorDirty, setEditorDirty] = useState(false)
  const [pendingSelection, setPendingSelection] = useState<string | null>(null)
  const [confirmRegenerate, setConfirmRegenerate] = useState(false)
  const [treeSearch, setTreeSearch] = useState("")
  const [enabledOnly, setEnabledOnly] = useState(false)
  const [sourceOnly, setSourceOnly] = useState(false)
  const [missingOnly, setMissingOnly] = useState(false)
  const [viewMode, setViewMode] = useState<"tree" | "overview">("tree")
  const [detailMode, setDetailMode] = useState<"edit" | "ai">("edit")
  const [treeExpandMode, setTreeExpandMode] = useState<"open" | "closed" | null>(null)
  const [nodeAction, setNodeAction] = useState<NodeAction | null>(null)

  const tree = useMemo(() => buildTree(outline.data ?? []), [outline.data])
  const visibleTree = useMemo(() => filterTree(tree, treeSearch, enabledOnly, sourceOnly, missingOnly), [tree, treeSearch, enabledOnly, sourceOnly, missingOnly])
  const selected = useMemo(() => outline.data?.find((n) => n.node_id === selectedId) ?? null, [outline.data, selectedId])
  const nextMissing = useMemo(() => {
    const nodes = outline.data ?? []
    const candidates = nodes.filter((node) => node.enabled !== false && node.readiness === "needs_confirmation")
    if (!candidates.length) return null
    const selectedIndex = candidates.findIndex((node) => node.node_id === selectedId)
    return candidates[selectedIndex >= 0 ? (selectedIndex + 1) % candidates.length : 0] ?? candidates[0]
  }, [outline.data, selectedId])
  const outlineStats = useMemo(() => {
    const nodes = outline.data ?? []
    return {
      total: nodes.length,
      enabled: nodes.filter((node) => node.enabled !== false).length,
      ready: nodes.filter((node) => node.readiness === "ready").length,
      sourced: nodes.filter((node) => Boolean(node.source_rules?.length)).length,
      targets: nodes.filter((node) => Number(node.target_word_count ?? 0) > 0).length,
      missing: nodes.filter((node) => Boolean(node.chapter_summary?.missing_information?.length || node.chapter_summary?.unresolved_items?.length)).length,
    }
  }, [outline.data])
  const outlineAction = outline.data?.length
    ? outlineStats.missing > 0
      ? { label: "先处理待确认项", detail: `${outlineStats.missing} 个节点还缺少项目资料或人工确认` }
      : outlineStats.ready < outlineStats.enabled
        ? { label: "检查目录状态", detail: `${outlineStats.enabled - outlineStats.ready} 个已启用节点还不能直接生成` }
        : { label: "目录已就绪", detail: "可以继续做局部 AI 优化，或进入章节生成" }
    : { label: "先生成项目目录", detail: "系统会结合模板、投标目录和项目概况创建可编辑目录" }

  useEffect(() => {
    if (!selectedId && outline.data?.length) setSelectedId(firstLeafNode(outline.data)?.node_id ?? outline.data.find((node) => node.enabled !== false)?.node_id ?? outline.data[0].node_id)
  }, [outline.data, selectedId])

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === project.project_id && job?.job_type === "directory_generation" && job?.status === "completed") void outline.reload()
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [outline.reload, project.project_id])

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      await startJob("directory_generation", { force: true })
      toast.success("目录生成已开始，可切换页面并在任务中心查看进度")
      setConfirmRegenerate(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    } finally {
      setGenerating(false)
    }
  }

  const requestGenerate = () => {
    if (outline.data?.length || editorDirty) setConfirmRegenerate(true)
    else void handleGenerate()
  }

  const requestSelection = (nodeId: string) => {
    if (editorDirty && nodeId !== selectedId) setPendingSelection(nodeId)
    else {
      setSelectedId(nodeId)
      setDetailMode("edit")
    }
  }

  const openNodeAction = (kind: NodeAction["kind"], node: OutlineNode) => {
    if (editorDirty && node.node_id !== selectedId) {
      setPendingSelection(node.node_id)
      return
    }
    setSelectedId(node.node_id)
    setNodeAction({ kind, node })
  }

  const handleEstimate = async () => {
    try {
      await estimateOutlineWordCounts(project.project_id)
      toast.success("已估算各章节目标字数")
      await outline.reload()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "估算失败")
    }
  }

  const handleDownloadOverview = async () => {
    try {
      const overview = await getOutlineOverview(project.project_id)
      const lines = ["# 施工组织设计目录纲要", "", `- 目录节点：${overview.node_count}`, `- 已生成纲要：${overview.summary_count}`, `- 待补信息节点：${overview.missing_information_count}`, ""]
      for (const raw of overview.nodes) {
        const node = raw as Record<string, unknown>
        const level = Math.max(1, Number(node.level ?? 1))
        const list = (value: unknown) => Array.isArray(value) ? value.filter(Boolean).join("；") : ""
        lines.push(`${"#".repeat(Math.min(6, level + 1))} ${String(node.title ?? "未命名章节")}`)
        if (node.overview) lines.push(`- 概括：${node.overview}`)
        if (list(node.scope)) lines.push(`- 范围：${list(node.scope)}`)
        if (list(node.key_points)) lines.push(`- 重点：${list(node.key_points)}`)
        if (list(node.source_basis)) lines.push(`- 依据：${list(node.source_basis)}`)
        const missing = [...(Array.isArray(node.missing_information) ? node.missing_information : []), ...(Array.isArray(node.unresolved_items) ? node.unresolved_items : [])]
        if (missing.length) lines.push(`- 待补/待确认：${missing.join("；")}`)
        lines.push("")
      }
      const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" }))
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `${project.project_id}-目录纲要.md`
      anchor.click()
      URL.revokeObjectURL(url)
      toast.success("目录纲要已下载")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "下载纲要失败")
    }
  }

  return (
    <div className="space-y-5">
      <div className={cn(
        "flex flex-col gap-3 rounded-[var(--radius)] border px-4 py-3 sm:flex-row sm:items-center sm:justify-between",
        outline.data?.length ? "border-primary/20 bg-primary/[0.04]" : "border-amber-300 bg-amber-50",
      )}>
        <div className="flex min-w-0 items-start gap-3">
          <div className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full", outline.data?.length ? "bg-primary/10 text-primary" : "bg-amber-100 text-amber-800")}>
            {outline.data?.length ? <ListTree className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">{outlineAction.label}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{outlineAction.detail}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 sm:pl-4">
          {outline.data?.length ? <span className="text-[11px] text-muted-foreground">完成后再进入章节生成</span> : null}
          <Button size="sm" variant={outline.data?.length ? "outline" : "accent"} onClick={requestGenerate} loading={generating || activeJob?.job_type === "directory_generation"} icon={<Wand2 className="h-3.5 w-3.5" />}>
            {outline.data?.length ? "重新生成目录" : "生成目录"}
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius)] border border-border bg-card px-3 py-2 text-[11px]">
        {[
          ["目录节点", outlineStats.total, "全部目录结构"],
          ["已启用", outlineStats.enabled, "参与后续生成"],
          ["可生成", outlineStats.ready, "依据和纲要已就绪"],
          ["有依据", outlineStats.sourced, "已关联投标资料"],
          ["已设字数", outlineStats.targets, "可控制篇幅"],
          ["待补信息", outlineStats.missing, "生成前需人工确认"],
        ].map(([label, value, hint]) => <span key={label} title={String(hint)} className="inline-flex items-center gap-1.5 text-muted-foreground"><span>{label}</span><strong className="text-sm text-foreground">{value}</strong></span>)}
      </div>
      {editorDirty ? <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius)] border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"><span>当前节点有未保存修改，切换节点或重新生成前请先保存。</span><span className="font-medium">未保存</span></div> : null}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(420px,0.9fr)] lg:items-start">
      <Card className="flex min-w-0 flex-col p-5">
        <SectionTitle
          title="目录树"
          description="选择一个节点，右侧只处理当前节点的编辑或 AI 优化。"
          right={<div className="flex items-center gap-1"><Button variant="ghost" size="icon" onClick={() => outline.reload()} aria-label="刷新目录"><RefreshCw className="h-3.5 w-3.5" /></Button><Button variant="ghost" size="icon" onClick={() => void handleDownloadOverview()} aria-label="下载目录纲要"><Download className="h-3.5 w-3.5" /></Button></div>}
        />
        <div className="mt-4 flex-1">
          {outline.loading ? (
            <LoadingBlock />
          ) : !outline.data?.length ? (
            <EmptyState
              icon={<ListTree className="h-7 w-7" />}
              title="尚未生成目录"
              description="点击“生成目录”，系统会根据模板、投标目录和项目概况创建项目自己的可编辑目录。"
              action={
                <Button onClick={requestGenerate} loading={generating} icon={<Wand2 className="h-4 w-4" />}>
                  立即生成
                </Button>
              }
            />
          ) : (
            <>
              <div className="mb-3 flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" /><TextInput value={treeSearch} onChange={(e) => setTreeSearch(e.target.value)} placeholder="搜索章节标题或概括" className="h-9 pl-8" /></div>
                  <Button variant="outline" size="sm" onClick={handleEstimate} icon={<Calculator className="h-3.5 w-3.5" />}>估算字数</Button>
                </div>
                <div className="flex items-center gap-1 rounded-[var(--radius)] border border-border bg-muted/30 p-1 self-start">
                  <button type="button" onClick={() => setViewMode("tree")} className={cn("rounded px-3 py-1.5 text-xs", viewMode === "tree" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground")}>目录树</button>
                  <button type="button" onClick={() => setViewMode("overview")} className={cn("rounded px-3 py-1.5 text-xs", viewMode === "overview" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground")}>纲要总览</button>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                  <label className="flex items-center gap-1.5"><input type="checkbox" checked={enabledOnly} onChange={(e) => setEnabledOnly(e.target.checked)} className="accent-[var(--color-primary)]" />仅看启用</label>
                  <label className="flex items-center gap-1.5"><input type="checkbox" checked={sourceOnly} onChange={(e) => setSourceOnly(e.target.checked)} className="accent-[var(--color-primary)]" />仅看有依据</label>
                  <label className="flex items-center gap-1.5"><input type="checkbox" checked={missingOnly} onChange={(e) => setMissingOnly(e.target.checked)} className="accent-[var(--color-primary)]" />仅看待补</label>
                  <span>显示 {countTreeNodes(visibleTree)} / {outline.data.length} 个节点</span>
                </div>
                {viewMode === "tree" ? <div className="flex items-center gap-2 text-[11px]"><button type="button" onClick={() => setTreeExpandMode("open")} className="text-primary hover:underline">展开全部</button><span className="text-border">|</span><button type="button" onClick={() => setTreeExpandMode("closed")} className="text-primary hover:underline">收起全部</button><span className="ml-auto text-muted-foreground">点击标题或编辑图标，右侧编辑</span></div> : null}
              </div>
              {viewMode === "tree" ? (
                <ul className="max-h-[min(62vh,720px)] overflow-y-auto overscroll-contain pr-1 flex flex-col gap-1">
                  {visibleTree.map((node) => (
                    <OutlineRow key={node.node_id} node={node} selectedId={selectedId} onSelect={requestSelection} onAction={openNodeAction} expandMode={treeExpandMode} />
                  ))}
                </ul>
              ) : <OutlineOverview nodes={outline.data ?? []} query={treeSearch} enabledOnly={enabledOnly} sourceOnly={sourceOnly} missingOnly={missingOnly} onSelect={requestSelection} />}
            </>
          )}
        </div>
      </Card>

      <div className="flex min-w-0 flex-col gap-5 lg:sticky lg:top-24">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] text-primary-foreground">2</span><span className="font-medium text-foreground">处理当前节点</span><ChevronRight className="h-3 w-3" /><span>保存目录或提交 AI 方案</span></div>
        {selected ? <OutlineNodeSummary node={selected} nextMissing={nextMissing} onSelectNext={nextMissing ? requestSelection : undefined} onOpenAi={() => setDetailMode("ai")} /> : null}
        <div className="rounded-[var(--radius)] border border-border bg-card p-1">
          <div className="grid grid-cols-2 gap-1">
            <button type="button" onClick={() => setDetailMode("edit")} className={cn("rounded px-3 py-2 text-xs font-medium", detailMode === "edit" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>编辑当前节点</button>
            <button type="button" onClick={() => setDetailMode("ai")} className={cn("rounded px-3 py-2 text-xs font-medium", detailMode === "ai" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted")}>AI 优化目录</button>
          </div>
        </div>
        {detailMode === "ai" ? <AIOutlinePanel projectId={project.project_id} scopeNode={selected} currentNodes={outline.data ?? []} onApplied={() => outline.reload()} /> : <NodeEditor
          key={selected?.node_id ?? "none"}
          projectId={project.project_id}
          node={selected}
          nodeCount={outline.data?.length ?? 0}
          onDirtyChange={setEditorDirty}
          onSaved={() => outline.reload()}
          onDeleted={() => {
            setSelectedId(null)
            outline.reload()
          }}
          onCreated={(nodeId) => {
            setSelectedId(nodeId)
            outline.reload()
          }}
          onMoved={() => outline.reload()}
        />}
        <Card className="p-5">
          <p className="text-sm font-medium text-foreground">目录确认完成</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">确认结构、字数和四模块后进入章节工作台。父节点可作为容器，主要生成叶子节点。</p>
          <Button className="mt-4 w-full" onClick={onNext} icon={<ArrowRight className="h-4 w-4" />}>
            进入章节生成
          </Button>
        </Card>
      </div>
      <ConfirmDialog
        open={Boolean(pendingSelection)}
        title="放弃未保存的修改？"
        description="当前节点还有未保存内容。继续切换会丢弃这些修改。"
        confirmLabel="放弃并切换"
        onClose={() => setPendingSelection(null)}
        onConfirm={() => { setSelectedId(pendingSelection); setDetailMode("edit"); setPendingSelection(null); setEditorDirty(false) }}
      />
      <ConfirmDialog
        open={confirmRegenerate}
        title="重新生成整个目录？"
        description="现有目录将被替换，已有章节版本仍会保留，但节点对应关系可能变化。建议先确认当前节点修改已保存。"
        confirmLabel="确认重新生成"
        danger
        loading={generating}
        onClose={() => setConfirmRegenerate(false)}
        onConfirm={() => void handleGenerate()}
      />
      {nodeAction?.kind === "edit" ? <MiniDialog title={`编辑节点：${nodeAction.node.title || "未命名节点"}`} onClose={() => setNodeAction(null)}>
        <NodeEditor
          projectId={project.project_id}
          node={nodeAction.node}
          nodeCount={outline.data?.length ?? 0}
          onDirtyChange={setEditorDirty}
          onSaved={() => { setNodeAction(null); outline.reload() }}
          onDeleted={() => { setNodeAction(null); setSelectedId(null); outline.reload() }}
          onCreated={(nodeId) => { setSelectedId(nodeId); outline.reload() }}
          onMoved={() => outline.reload()}
          onRequestDelete={() => setNodeAction({ kind: "delete", node: nodeAction.node })}
        />
      </MiniDialog> : null}
      {nodeAction?.kind === "children" ? <ChildNodesDialog projectId={project.project_id} parent={nodeAction.node} childCount={tree.find((item) => item.node_id === nodeAction.node.node_id)?._children.length ?? 0} onClose={() => setNodeAction(null)} onChanged={() => { setNodeAction(null); outline.reload() }} /> : null}
      {nodeAction?.kind === "delete" ? <DeleteNodeDialog projectId={project.project_id} node={nodeAction.node} childCount={tree.find((item) => item.node_id === nodeAction.node.node_id)?._children.length ?? 0} onClose={() => setNodeAction(null)} onDeleted={() => { setNodeAction(null); setSelectedId(null); outline.reload() }} /> : null}
      </div>
    </div>
  )
}

function OutlineRow({ node, selectedId, onSelect, onAction, expandMode }: { node: TreeNode; selectedId: string | null; onSelect: (id: string) => void; onAction: (kind: NodeAction["kind"], node: OutlineNode) => void; expandMode: "open" | "closed" | null }) {
  const [open, setOpen] = useState((node.level ?? 1) <= 1)
  useEffect(() => {
    if (expandMode) setOpen(expandMode === "open")
  }, [expandMode])
  const hasChildren = node._children.length > 0
  const isSelected = node.node_id === selectedId
  const disabled = node.enabled === false
  return (
    <li>
      <div
        className={cn("group flex items-center gap-1.5 rounded-[var(--radius)] border px-2 py-2 transition-colors", isSelected ? "border-primary/40 bg-primary/[0.05]" : "border-transparent hover:bg-muted/50")}
        style={{ marginLeft: (node.level ?? 1) > 1 ? (node.level - 1) * 14 : 0 }}
      >
        {hasChildren ? (
          <button onClick={() => setOpen((v) => !v)} className="rounded p-0.5 text-muted-foreground hover:bg-muted" aria-label={open ? "折叠" : "展开"}>
            <ChevronRight className={cn("h-4 w-4 transition-transform", open && "rotate-90")} />
          </button>
        ) : (
          <span className="w-5" />
        )}
        <button onClick={() => onSelect(node.node_id)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className="min-w-0 flex-1">
            <span className={cn("block truncate text-sm", disabled ? "text-muted-foreground/60 line-through" : "text-foreground")}>{node.title || "未命名章节"}</span>
          </span>
          {node.chapter_summary?.coverage_status ? (
            <Badge tone={node.chapter_summary.coverage_status === "grounded" ? "success" : node.chapter_summary.coverage_status === "aggregate" ? "info" : "warning"} className="shrink-0">
              {node.chapter_summary.coverage_status === "grounded" ? "有依据" : node.chapter_summary.coverage_status === "aggregate" ? "结构章" : "待补来源"}
            </Badge>
          ) : null}
          {node.readiness ? <Badge tone={node.readiness === "ready" ? "success" : node.readiness === "needs_confirmation" ? "warning" : "info"} className="shrink-0">
            {node.readiness === "ready" ? "可生成" : node.readiness === "needs_confirmation" ? "待确认" : node.readiness === "container" ? "目录容器" : "已禁用"}
          </Badge> : null}
          {node.target_word_count ? <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{node.target_word_count} 字</span> : null}
          {hasChildren ? <span className="shrink-0 text-[10px] text-muted-foreground">{node._children.length} 节</span> : null}
        </button>
        <button
          type="button"
          onClick={() => onSelect(node.node_id)}
          className="shrink-0 rounded p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-primary/10 hover:text-primary group-hover:opacity-100 focus-visible:opacity-100"
          aria-label={`编辑${node.title || "节点"}`}
          title="编辑节点"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      </div>
      {isSelected ? <div className="flex flex-wrap items-center gap-1 border-x border-b border-primary/20 bg-primary/[0.03] px-8 py-1.5" role="toolbar" aria-label="节点操作">
        <span className="mr-1 text-[10px] text-muted-foreground">当前节点操作：</span>
        <button type="button" onClick={() => onAction("edit", node)} className="rounded px-2 py-1 text-[11px] text-muted-foreground hover:bg-primary/10 hover:text-primary">编辑</button>
        <button type="button" onClick={() => onAction("children", node)} className="rounded px-2 py-1 text-[11px] text-muted-foreground hover:bg-primary/10 hover:text-primary">生成子节点</button>
        <button type="button" onClick={() => onAction("delete", node)} className="rounded px-2 py-1 text-[11px] text-muted-foreground hover:bg-red-50 hover:text-red-700">删除节点</button>
      </div> : null}
      {hasChildren && open ? (
        <ul className="flex flex-col gap-1">
          {node._children.map((child) => (
            <OutlineRow key={child.node_id} node={child} selectedId={selectedId} onSelect={onSelect} onAction={onAction} expandMode={expandMode} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function OutlineOverview({ nodes, query, enabledOnly, sourceOnly, missingOnly, onSelect }: { nodes: OutlineNode[]; query: string; enabledOnly: boolean; sourceOnly: boolean; missingOnly: boolean; onSelect: (id: string) => void }) {
  const needle = query.trim().toLowerCase()
  const items = nodes.filter((node) => {
    const summary = node.chapter_summary
    const text = `${node.title} ${summary?.overview ?? ""} ${summary?.generated_overview ?? ""} ${(summary?.key_points ?? []).join(" ")}`.toLowerCase()
    const hasMissing = Boolean(summary?.missing_information?.length || summary?.unresolved_items?.length || node.manual_fill?.length)
    return (!needle || text.includes(needle)) && (!enabledOnly || node.enabled !== false) && (!sourceOnly || Boolean(node.source_rules?.length)) && (!missingOnly || hasMissing)
  })
  return (
    <div className="max-h-[min(62vh,720px)] overflow-y-auto space-y-2 pr-1">
      <p className="text-[11px] leading-relaxed text-muted-foreground">这是当前目录的生成前纲要校核视图。先看每节要写什么、依据是否足够、还缺哪些人工信息，再进入章节生成。</p>
      {items.map((node) => {
        const summary = node.chapter_summary
        const scope = summary?.scope?.slice(0, 3) ?? []
        const points = summary?.key_points?.slice(0, 3) ?? []
        const missing = [...(summary?.missing_information ?? []), ...(summary?.unresolved_items ?? [])].slice(0, 3)
        return (
          <button key={node.node_id} type="button" onClick={() => onSelect(node.node_id)} className="w-full rounded-[var(--radius)] border border-border bg-card p-3 text-left hover:border-primary/40">
            <div className="flex items-start justify-between gap-3" style={{ paddingLeft: Math.max(0, (node.level ?? 1) - 1) * 12 }}>
              <span className="min-w-0 text-sm font-medium text-foreground">{node.title || "未命名章节"}</span>
              <span className="shrink-0 text-[11px] text-muted-foreground">{node.target_word_count ? `${node.target_word_count} 字` : "未设字数"}</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{summary?.generated_overview || summary?.overview || "尚无章节概括"}</p>
            {scope.length ? <p className="mt-1 text-[11px] leading-relaxed text-foreground/80"><span className="text-muted-foreground">范围：</span>{scope.join("；")}</p> : null}
            {points.length ? <p className="mt-1 text-[11px] leading-relaxed text-foreground/80"><span className="text-muted-foreground">重点：</span>{points.join("；")}</p> : null}
            {missing.length ? <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-warning)]"><span>待补：</span>{missing.join("；")}</p> : null}
            {node.readiness_reasons?.length ? <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-warning)]"><span>状态：</span>{node.readiness_reasons.slice(0, 3).join("；")}</p> : null}
          </button>
        )
      })}
      {!items.length ? <p className="py-8 text-center text-xs text-muted-foreground">没有匹配的纲要节点。</p> : null}
    </div>
  )
}

function OutlineNodeSummary({ node, nextMissing, onSelectNext, onOpenAi }: { node: OutlineNode; nextMissing: OutlineNode | null; onSelectNext?: (id: string) => void; onOpenAi?: () => void }) {
  const summary = node.chapter_summary
  const hints = summary?.writing_unit_hints ?? []
  const unresolved = summary?.unresolved_items ?? []
  const missing = summary?.missing_information ?? []
  const sourceBasis = summary?.source_basis ?? []
  return (
    <div className="border-y border-border bg-muted/25 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{node.title || "未命名章节"}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">本章生成概括 · 层级 {node.level ?? 1}</p>
        </div>
        <span className={cn("shrink-0 rounded-full px-2 py-1 text-[11px]", node.readiness === "ready" ? "bg-emerald-100 text-emerald-800" : node.readiness === "needs_confirmation" ? "bg-amber-100 text-amber-800" : "bg-muted text-muted-foreground")}>
          {summary?.generation_role === "container" ? "仅作目录容器" : node.readiness === "needs_confirmation" ? "待确认后生成" : "可生成章节"}
        </span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        {summary?.generated_overview || summary?.overview || "尚无章节纲要，可先让 AI 生成一份待审阅方案。"}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {onOpenAi ? <Button size="sm" variant="accent" onClick={onOpenAi} icon={<Sparkles className="h-3.5 w-3.5" />}>
          生成本章纲要
        </Button> : null}
        <span className="text-[11px] text-muted-foreground">AI 只生成待审阅方案，不会直接覆盖当前目录</span>
      </div>
      {(hints.length || sourceBasis.length || missing.length || unresolved.length) ? <details className="mt-2 rounded border border-border/70 bg-background/30 px-2.5 py-2 text-[11px]">
        <summary className="cursor-pointer select-none text-muted-foreground">查看本章依据与待处理项</summary>
        {hints.length ? <p className="mt-2 text-muted-foreground">建议展开：{hints.slice(0, 5).join(" · ")}</p> : null}
        {sourceBasis.length ? <p className="mt-1 text-muted-foreground">依据：{sourceBasis.slice(0, 3).join(" · ")}</p> : null}
        {missing.length ? <p className="mt-1 text-[var(--color-warning)]">待补资料：{missing.slice(0, 3).join(" · ")}</p> : null}
        {unresolved.length ? <p className="mt-1 text-[var(--color-warning)]">待确认：{unresolved.slice(0, 3).join(" · ")}</p> : null}
      </details> : null}
      {nextMissing && onSelectNext ? <Button size="sm" variant="ghost" className="mt-2 px-0 text-xs text-primary" onClick={() => onSelectNext(nextMissing.node_id)}>
        处理下一个待确认节点：{nextMissing.title}
      </Button> : null}
    </div>
  )
}

function NodeEditor({
  projectId,
  node,
  nodeCount,
  onSaved,
  onDeleted,
  onCreated,
  onMoved,
  onDirtyChange,
  onRequestDelete,
}: {
  projectId: string
  node: OutlineNode | null
  nodeCount: number
  onSaved: () => void
  onDeleted: () => void
  onCreated: (nodeId: string) => void
  onMoved: () => void
  onDirtyChange: (dirty: boolean) => void
  onRequestDelete?: () => void
}) {
  const toast = useToast()
  const [title, setTitle] = useState(node?.title ?? "")
  const [wordCount, setWordCount] = useState(node?.target_word_count?.toString() ?? "")
  const [enabled, setEnabled] = useState(node?.enabled !== false)
  const [sourceRules, setSourceRules] = useState(joinLines(node?.source_rules))
  const [autoFill, setAutoFill] = useState(joinLines(node?.auto_fill))
  const [manualFill, setManualFill] = useState(joinLines(node?.manual_fill))
  const [specialNotes, setSpecialNotes] = useState(joinLines(node?.special_notes))
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState("")
  const [confirmDelete, setConfirmDelete] = useState(false)
  const dirty = Boolean(node) && (
    title !== (node?.title ?? "") || wordCount !== (node?.target_word_count?.toString() ?? "") ||
    enabled !== (node?.enabled !== false) || sourceRules !== joinLines(node?.source_rules) ||
    autoFill !== joinLines(node?.auto_fill) || manualFill !== joinLines(node?.manual_fill) ||
    specialNotes !== joinLines(node?.special_notes)
  )

  useEffect(() => {
    onDirtyChange(dirty)
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    window.addEventListener("beforeunload", beforeUnload)
    return () => { window.removeEventListener("beforeunload", beforeUnload); onDirtyChange(false) }
  }, [dirty, onDirtyChange])

  const createNode = async (asChild: boolean) => {
    if (!newTitle.trim()) {
      toast.error("请填写新节点标题")
      return
    }
    setCreating(true)
    try {
      const created = await createOutlineNode(projectId, {
        title: newTitle.trim(),
        parent_id: asChild ? node?.node_id ?? null : node?.parent_id ?? null,
        level: asChild ? (node?.level ?? 0) + 1 : node?.level ?? 1,
        sort_order: nodeCount + 1,
        enabled: true,
        source_rules: [],
        auto_fill: [],
        manual_fill: [],
        special_notes: [],
      })
      setNewTitle("")
      toast.success("节点已新增")
      onCreated(created.node_id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "新增失败")
    } finally {
      setCreating(false)
    }
  }

  const save = async () => {
    if (!node) return
    setSaving(true)
    try {
      await updateOutlineNode(projectId, node.node_id, {
        title,
        enabled,
        target_word_count: wordCount ? Number(wordCount) : null,
        source_rules: splitLines(sourceRules),
        auto_fill: splitLines(autoFill),
        manual_fill: splitLines(manualFill),
        special_notes: splitLines(specialNotes),
      })
      toast.success("节点已保存")
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!node) return
    setDeleting(true)
    try {
      await deleteOutlineNode(projectId, node.node_id)
      toast.success("节点已删除")
      onDeleted()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeleting(false)
    }
  }

  const move = async (direction: "up" | "down" | "indent" | "outdent") => {
    if (!node) return
    try {
      await moveOutlineNode(projectId, node.node_id, direction)
      toast.success("目录层级已调整")
      onMoved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "调整层级失败")
    }
  }

  return (
    <Card className="p-5">
      <SectionTitle title="节点编辑" description={node ? `层级 ${node.level ?? 1}` : "选择左侧节点后可编辑四模块和字数"} />
      <div className="mt-4 flex flex-col gap-4">
        {!node ? <p className="text-sm text-muted-foreground">也可以直接新增一个根节点。</p> : null}
        {node ? (
          <>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">章节标题</label>
              <TextInput value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="flex items-end gap-3">
              <div className="flex-1">
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">目标字数</label>
                <TextInput type="number" value={wordCount} onChange={(e) => setWordCount(e.target.value)} placeholder="不限定" />
              </div>
              <label className="flex h-10 cursor-pointer items-center gap-2 rounded-[var(--radius)] border border-border px-3 text-sm">
                <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-[var(--color-primary)]" />
                启用
              </label>
            </div>
            <details className="rounded-[var(--radius)] border border-border bg-background/30 px-3 py-2">
              <summary className="cursor-pointer select-none text-xs font-medium text-foreground">生成内容设置 <span className="ml-1 text-[10px] font-normal text-muted-foreground">来源、自动补充、人工待确认</span></summary>
              <div className="mt-3 flex flex-col gap-4">
                <ModuleText label="[主要来源]" value={sourceRules} onChange={setSourceRules} />
                <ModuleText label="[自动补充]" value={autoFill} onChange={setAutoFill} />
                <ModuleText label="[人工补充需补充]" value={manualFill} onChange={setManualFill} />
                <ModuleText label="[特殊备注]" value={specialNotes} onChange={setSpecialNotes} rows={2} />
              </div>
            </details>
            <div className="flex items-center gap-2">
              <Button onClick={save} loading={saving} icon={<Save className="h-4 w-4" />} className="flex-1">
                保存修改
              </Button>
              <Button variant="danger" onClick={() => onRequestDelete ? onRequestDelete() : setConfirmDelete(true)} loading={deleting} icon={<Trash2 className="h-4 w-4" />}>
                删除
              </Button>
            </div>
            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              <Button size="sm" variant="outline" onClick={() => void move("up")} icon={<ArrowUp className="h-3.5 w-3.5" />}>上移</Button>
              <Button size="sm" variant="outline" onClick={() => void move("down")} icon={<ArrowDown className="h-3.5 w-3.5" />}>下移</Button>
              <Button size="sm" variant="outline" onClick={() => void move("indent")} icon={<CornerDownLeft className="h-3.5 w-3.5" />}>变为子级</Button>
              <Button size="sm" variant="outline" onClick={() => void move("outdent")} icon={<CornerUpLeft className="h-3.5 w-3.5" />}>取消子级</Button>
            </div>
          </>
        ) : null}
        <div className="rounded-[var(--radius)] border border-border bg-muted/30 p-3">
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">新增节点</label>
          <div className="flex gap-2">
            <TextInput value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="输入新章节标题" className="h-9" />
            <Button size="sm" variant="outline" loading={creating} onClick={() => createNode(false)} icon={<Plus className="h-3.5 w-3.5" />}>
              同级
            </Button>
            <Button size="sm" disabled={!node} loading={creating} onClick={() => createNode(true)} icon={<Plus className="h-3.5 w-3.5" />}>
              子级
            </Button>
          </div>
        </div>
        <ConfirmDialog
          open={confirmDelete}
          title="删除目录节点？"
          description="该节点及其下级目录将从当前目录中删除。已生成版本不会自动并入其他章节。"
          confirmLabel="确认删除"
          danger
          loading={deleting}
          onClose={() => setConfirmDelete(false)}
          onConfirm={() => void remove()}
        />
      </div>
    </Card>
  )
}

function MiniDialog({ title, description, onClose, children }: { title: string; description?: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-[65] flex items-center justify-center bg-black/35 p-4" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="flex max-h-[min(88vh,860px)] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius)] border border-border bg-background shadow-2xl" role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0"><h2 className="text-base font-semibold text-foreground">{title}</h2>{description ? <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p> : null}</div>
          <Button size="icon" variant="ghost" onClick={onClose} aria-label="关闭窗口"><X className="h-4 w-4" /></Button>
        </div>
        <div className="min-h-0 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}

function ChildNodesDialog({ projectId, parent, childCount, onClose, onChanged }: { projectId: string; parent: OutlineNode; childCount: number; onClose: () => void; onChanged: () => void }) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const [manualTitles, setManualTitles] = useState("")
  const [prompt, setPrompt] = useState("")
  const [creating, setCreating] = useState(false)
  const [proposal, setProposal] = useState<AIProposal | null>(null)
  const [excludedNodeIds, setExcludedNodeIds] = useState<string[]>([])
  const aiLoading = activeJob?.job_type === "outline_proposal" && String(activeJob.payload.scope_node_id ?? "") === parent.node_id

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === projectId && job?.job_type === "outline_proposal" && String(job?.payload?.scope_node_id ?? "") === parent.node_id && job?.status === "completed") {
        setProposal(job.result as AIProposal)
        setExcludedNodeIds([])
      }
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [parent.node_id, projectId])

  const createManual = async () => {
    const titles = splitLines(manualTitles)
    if (!titles.length) {
      toast.error("请先逐行填写要新增的子节点标题")
      return
    }
    setCreating(true)
    try {
      for (const [index, title] of titles.entries()) {
        await createOutlineNode(projectId, { title, parent_id: parent.node_id, level: (parent.level ?? 1) + 1, sort_order: childCount + index + 1, enabled: true, source_rules: [], auto_fill: [], manual_fill: [], special_notes: [] })
      }
      toast.success(`已新增 ${titles.length} 个子节点`)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "新增子节点失败")
    } finally {
      setCreating(false)
    }
  }

  const generateWithAI = async () => {
    if (!prompt.trim()) {
      toast.error("请用一句话说明希望补充什么子结构")
      return
    }
    try {
      await startJob("outline_proposal", { suggestion: `仅为“${parent.title}”生成子节点，不修改父节点及其他目录。用户要求：${prompt.trim()}`, scope_node_id: parent.node_id, scope_mode: "node", preserve_top_level: true, max_changes: 12, mode: "balanced" })
      toast.success("子结构建议已开始生成，完成后会在窗口内预览")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成子结构失败")
    }
  }

  const applyProposal = async () => {
    if (!proposal) return
    setCreating(true)
    try {
      await applyOutlineProposal(projectId, proposal.id, { exclude_node_ids: excludedNodeIds })
      toast.success("AI 子结构已应用")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "应用子结构失败")
    } finally {
      setCreating(false)
    }
  }

  return (
    <MiniDialog title={`生成子节点：${parent.title || "未命名节点"}`} description="可以手动逐行添加，也可以用一句话让 AI 生成候选子结构；AI 结果需要确认后才会写入目录。" onClose={onClose}>
      <div className="space-y-4">
        <section className="rounded-[var(--radius)] border border-border bg-card p-3">
          <p className="text-xs font-semibold text-foreground">方式一：手动添加</p>
          <p className="mt-1 text-[11px] text-muted-foreground">每行一个标题，适合你已经明确知道目录层级的情况。</p>
          <TextArea className="mt-3" rows={5} value={manualTitles} onChange={(event) => setManualTitles(event.target.value)} placeholder={"施工准备\n钻孔施工\n灌浆施工\n质量检查"} />
          <div className="mt-3 flex justify-end"><Button size="sm" onClick={() => void createManual()} loading={creating} icon={<Plus className="h-3.5 w-3.5" />}>直接新增子节点</Button></div>
        </section>
        <section className="rounded-[var(--radius)] border border-accent/30 bg-accent/[0.04] p-3">
          <p className="text-xs font-semibold text-foreground">方式二：AI 生成候选结构</p>
          <p className="mt-1 text-[11px] text-muted-foreground">只需描述意图，例如“按施工准备、钻孔、灌浆、检查和异常处理展开”。</p>
          <TextArea className="mt-3" rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="简短描述希望补充的子结构" />
          <div className="mt-3 flex justify-end"><Button size="sm" variant="accent" onClick={() => void generateWithAI()} loading={aiLoading} icon={<Sparkles className="h-3.5 w-3.5" />}>让 AI 生成子结构</Button></div>
          {proposal ? <div className="mt-4 border-t border-border pt-3"><div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-accent">AI 候选子结构</p><span className="text-[10px] text-muted-foreground">可逐项取消</span></div><div className="mt-2"><OutlineProposalPreview preview={proposal.preview} excludedNodeIds={excludedNodeIds} onToggle={(nodeId) => setExcludedNodeIds((current) => current.includes(nodeId) ? current.filter((id) => id !== nodeId) : [...current, nodeId])} /></div><div className="mt-3 flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => setProposal(null)}>重新描述</Button><Button size="sm" variant="accent" onClick={() => void applyProposal()} loading={creating} disabled={!proposalHasChanges(proposal.preview)}>确认加入目录</Button></div></div> : null}
        </section>
      </div>
    </MiniDialog>
  )
}

function DeleteNodeDialog({ projectId, node, childCount, onClose, onDeleted }: { projectId: string; node: OutlineNode; childCount: number; onClose: () => void; onDeleted: () => void }) {
  const toast = useToast()
  const [deleting, setDeleting] = useState<"node" | "subtree" | null>(null)
  const remove = async (mode: "node" | "subtree") => {
    setDeleting(mode)
    try {
      await deleteOutlineNode(projectId, node.node_id, mode)
      toast.success(mode === "node" ? "节点已删除，子节点已提升" : "节点及其子结构已删除")
      onDeleted()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeleting(null)
    }
  }
  return (
    <MiniDialog title={`删除节点：${node.title || "未命名节点"}`} description="请选择删除范围。这个操作会改变目录树结构，已有章节版本不会自动并入其他节点。" onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <button type="button" onClick={() => void remove("node")} disabled={Boolean(deleting)} className="rounded-[var(--radius)] border border-border bg-card p-4 text-left transition-colors hover:border-primary/50 hover:bg-primary/[0.04] disabled:opacity-60">
          <p className="text-sm font-semibold text-foreground">仅删除当前节点</p>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">保留 {childCount} 个直接子节点，并将它们提升到当前节点的父级。</p>
          {deleting === "node" ? <p className="mt-3 text-[11px] text-primary">正在删除...</p> : null}
        </button>
        <button type="button" onClick={() => void remove("subtree")} disabled={Boolean(deleting)} className="rounded-[var(--radius)] border border-red-200 bg-red-50/60 p-4 text-left transition-colors hover:border-red-400 hover:bg-red-50 disabled:opacity-60">
          <p className="text-sm font-semibold text-red-800">删除整个子结构</p>
          <p className="mt-2 text-xs leading-relaxed text-red-700/80">删除当前节点及其全部下级目录，适合确认整段结构都不再需要的情况。</p>
          {deleting === "subtree" ? <p className="mt-3 text-[11px] text-red-700">正在删除...</p> : null}
        </button>
      </div>
      <div className="mt-4 flex justify-end"><Button size="sm" variant="outline" onClick={onClose} disabled={Boolean(deleting)}>暂不删除</Button></div>
    </MiniDialog>
  )
}

function ModuleText({ label, value, onChange, rows = 3 }: { label: string; value: string; onChange: (v: string) => void; rows?: number }) {
  const count = splitLines(value).length
  return (
    <div>
      <label className="mb-1.5 flex items-center justify-between text-xs font-medium text-muted-foreground"><span>{label}</span><span className="font-normal">{count ? `${count} 条` : "未填写"}</span></label>
      <TextArea rows={rows} value={value} onChange={(e) => onChange(e.target.value)} placeholder="一行一条，可留空" />
    </div>
  )
}

function AIOutlinePanel({ projectId, scopeNode, currentNodes, onApplied }: { projectId: string; scopeNode: OutlineNode | null; currentNodes: OutlineNode[]; onApplied: () => void }) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const [suggestion, setSuggestion] = useState("")
  const [mode, setMode] = useState<RefineMode>("balanced")
  const [loading, setLoading] = useState(false)
  const [proposal, setProposal] = useState<AIProposal | null>(null)
  const [proposalHistory, setProposalHistory] = useState<AIProposal[]>([])
  const [applying, setApplying] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [scopeMode, setScopeMode] = useState<"node" | "subtree" | "all">(scopeNode ? "subtree" : "all")
  const [preserveTopLevel, setPreserveTopLevel] = useState(true)
  const [maxChanges, setMaxChanges] = useState(20)
  const [excludedNodeIds, setExcludedNodeIds] = useState<string[]>([])
  const [snapshotId, setSnapshotId] = useState<string | null>(null)
  const [compareOpen, setCompareOpen] = useState(false)

  useEffect(() => {
    void listOutlineProposals(projectId, "all").then((items) => {
      setProposalHistory(items)
      const pending = items.find((item) => item.status === "pending")
      if (pending) setProposal(pending)
    }).catch(() => undefined)
  }, [projectId])

  const proposeRefine = async () => {
    setLoading(true)
    setProposal(null)
    try {
      await startJob("outline_refine", { mode, use_local_corpus: true, project_type: "auto", scope_node_id: scopeMode === "all" ? null : scopeNode?.node_id, scope_mode: scopeMode, preserve_top_level: preserveTopLevel, max_changes: maxChanges })
      toast.success("目录精修分析已开始，完成后会自动显示方案")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成精修建议失败")
    } finally {
      setLoading(false)
    }
  }

  const proposeCustom = async (customSuggestion = suggestion, requestedScope: "node" | "subtree" | "all" = scopeMode) => {
    if (!customSuggestion.trim()) {
      toast.error("请描述目录调整意图")
      return
    }
    setLoading(true)
    setProposal(null)
    try {
      const scopedSuggestion = `用户要求：${customSuggestion.trim()}`
      await startJob("outline_proposal", {
        suggestion: scopedSuggestion,
        scope_node_id: requestedScope === "all" ? null : scopeNode?.node_id,
        scope_mode: requestedScope,
        preserve_top_level: preserveTopLevel,
        max_changes: maxChanges,
        mode,
      })
      toast.success("目录调整分析已开始，完成后会自动显示方案")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成方案失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id === projectId && ["outline_refine", "outline_proposal"].includes(job?.job_type) && job?.status === "completed") {
        const nextProposal = job.result as AIProposal
        setProposal(nextProposal)
        setProposalHistory((current) => [nextProposal, ...current.filter((item) => item.id !== nextProposal.id)])
        setExcludedNodeIds([])
        setSnapshotId(null)
      }
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [projectId])

  const apply = async () => {
    if (!proposal) return
    if (proposalIsBroad(proposal.preview)) {
      toast.error("该方案影响范围过大，请缩小调整要求后重新生成")
      return
    }
    setCompareOpen(true)
  }

  const applyConfirmed = async () => {
    if (!proposal) return
    setApplying(true)
    try {
      const applied = await applyOutlineProposal(projectId, proposal.id, { exclude_node_ids: excludedNodeIds })
      setCompareOpen(false)
      setSnapshotId(applied.snapshot_id ?? null)
      toast.success("方案已应用")
      const appliedProposal = { ...proposal, status: "applied", applied_at: new Date().toISOString() }
      setProposal(appliedProposal)
      setProposalHistory((current) => current.map((item) => item.id === proposal.id ? appliedProposal : item))
      setSuggestion("")
      onApplied()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "应用失败")
    } finally {
      setApplying(false)
    }
  }

  const reject = async () => {
    if (!proposal) return
    setRejecting(true)
    try {
      await rejectOutlineProposal(projectId, proposal.id)
      toast.success("已忽略该目录建议")
      setProposalHistory((current) => current.map((item) => item.id === proposal.id ? { ...item, status: "rejected" } : item))
      setProposal(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "忽略建议失败")
    } finally {
      setRejecting(false)
    }
  }

  return (
    <Card className="p-5">
      <SectionTitle title="AI 优化目录" description="描述你想怎么改，AI 先给出变更预览，你确认后才会写入目录。" />
      <div className="mt-4 flex flex-col gap-3">
        <div className="rounded-[var(--radius)] border border-primary/20 bg-primary/[0.04] p-3 text-xs text-muted-foreground">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-medium text-primary">
            <span>1. 选择范围</span><ChevronRight className="h-3 w-3" /><span>2. 描述意图</span><ChevronRight className="h-3 w-3" /><span>3. 审阅并应用</span>
          </div>
          <p className="mt-2">当前节点：<span className="font-medium text-foreground">{scopeNode?.title ?? "未选择，将作用于整个目录"}</span></p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {["node", "subtree", "all"].map((item) => (
            <button key={item} type="button" disabled={item !== "all" && !scopeNode} onClick={() => setScopeMode(item as typeof scopeMode)} className={cn("rounded-[var(--radius)] border px-2 py-2 text-xs", scopeMode === item ? "border-primary bg-primary/[0.06] text-primary" : "border-border text-muted-foreground")}>{item === "node" ? "仅当前节点" : item === "subtree" ? "当前节点及子级" : "整个目录"}</button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={preserveTopLevel} onChange={(e) => setPreserveTopLevel(e.target.checked)} className="accent-[var(--color-primary)]" />保留一级目录</label>
          <label className="flex items-center gap-1.5">最多变更 <TextInput type="number" min={1} max={100} value={maxChanges} onChange={(e) => setMaxChanges(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} className="h-7 w-16 px-2" /> 个节点</label>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(["balanced", "conservative", "aggressive"] as RefineMode[]).map((item) => (
            <button
              key={item}
              onClick={() => setMode(item)}
              className={cn("rounded-[var(--radius)] border px-2 py-2 text-xs font-medium transition-colors", mode === item ? "border-primary bg-primary/[0.06] text-primary" : "border-border text-muted-foreground hover:bg-muted/50")}
            >
              {item === "balanced" ? "均衡" : item === "conservative" ? "保守" : "积极"}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <span className="w-full text-xs font-medium text-foreground">告诉 AI 你希望目录怎么调整</span>
          {[
            "补足工艺层级，并保持现有一级目录不变",
            "合并重复章节，保留来源更充分的节点",
            "补足质量、安全和验收闭环",
            "依据投标目录纠正标题与章节归属",
          ].map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setSuggestion(item)}
              className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-primary"
            >
              {item}
            </button>
          ))}
        </div>
        <TextArea rows={4} value={suggestion} onChange={(e) => setSuggestion(e.target.value)} placeholder="例如：把灌浆施工拆成施工准备、钻孔、灌浆、质量检查和异常处理几个子节，保留现有一级目录。" />
        <Button onClick={() => void proposeCustom()} loading={loading || activeJob?.job_type === "outline_proposal"} disabled={!suggestion.trim()} variant="accent" icon={<Wand2 className="h-4 w-4" />}>
          提交 AI 优化意图
        </Button>
        <Button onClick={proposeRefine} loading={loading || activeJob?.job_type === "outline_refine"} variant="outline" icon={<Sparkles className="h-4 w-4" />}>
          让 AI 自动检查目录完整性
        </Button>
        {scopeNode ? <Button onClick={() => void proposeCustom("请补全当前节点的章节纲要：明确施工对象与工序展开，补充质量控制、安全环保、验收记录和异常处置闭环；将缺少的工程量、图纸、参数、频率、阈值等列入人工待确认项，不编造项目事实。", "node")} loading={loading || activeJob?.job_type === "outline_proposal"} variant="accent" icon={<Sparkles className="h-4 w-4" />}>
          按默认要求生成本章纲要
        </Button> : null}
        {proposal ? (
          <div className="rounded-[var(--radius)] border border-accent/30 bg-accent/[0.05] p-3">
            <p className="text-xs font-medium text-accent">方案预览</p>
            <OutlineProposalPreview preview={proposal.preview} excludedNodeIds={excludedNodeIds} onToggle={(nodeId) => setExcludedNodeIds((current) => current.includes(nodeId) ? current.filter((id) => id !== nodeId) : [...current, nodeId])} />
            {proposal.status === "pending" ? <div className="mt-3 grid grid-cols-2 gap-2">
              <Button size="sm" variant="outline" onClick={reject} loading={rejecting}>忽略此方案</Button>
              <Button size="sm" onClick={apply} loading={applying} disabled={proposalIsBroad(proposal.preview) || !proposalHasChanges(proposal.preview)}>确认并应用</Button>
            </div> : <p className="mt-3 text-xs text-emerald-700">本方案已应用。目录已更新，必要时可撤销本次修改。</p>}
            {snapshotId ? <Button size="sm" variant="ghost" onClick={async () => { try { await restoreOutlineSnapshot(projectId, snapshotId); toast.success("已撤销本次目录修改"); setSnapshotId(null); onApplied() } catch (err) { toast.error(err instanceof Error ? err.message : "撤销失败") } }} icon={<RotateCcw className="h-3.5 w-3.5" />}>撤销本次修改</Button> : null}
          </div>
        ) : null}
        {proposalHistory.length ? <details className="rounded-[var(--radius)] border border-border bg-background/30 px-3 py-2">
          <summary className="cursor-pointer select-none text-xs font-medium text-foreground">方案记录 <span className="ml-1 text-[10px] font-normal text-muted-foreground">{proposalHistory.length} 条，点击可重新查看</span></summary>
          <div className="mt-2 flex flex-col gap-1.5">
            {proposalHistory.slice(0, 8).map((item) => <button key={item.id} type="button" onClick={() => { setProposal(item); setExcludedNodeIds([]); setSnapshotId(null) }} className="flex items-center justify-between gap-3 rounded border border-border/70 px-2.5 py-2 text-left hover:border-primary/40">
              <span className="min-w-0 truncate text-[11px] text-foreground">{item.suggestion.replace(/^用户要求：/, "") || "未命名目录建议"}</span>
              <span className={cn("shrink-0 text-[10px]", item.status === "pending" ? "text-amber-700" : item.status === "applied" ? "text-emerald-700" : "text-muted-foreground")}>{proposalStatusLabel(item.status)} · {formatProposalTime(item.created_at)}</span>
            </button>)}
          </div>
        </details> : null}
      </div>
      {compareOpen && proposal ? <OutlineCompareDrawer currentNodes={currentNodes} proposal={proposal} excludedNodeIds={excludedNodeIds} onClose={() => setCompareOpen(false)} onConfirm={applyConfirmed} applying={applying} /> : null}
    </Card>
  )
}

function proposalStatusLabel(status: string): string {
  return status === "pending" ? "待审阅" : status === "applied" ? "已应用" : status === "rejected" ? "已忽略" : status
}

function formatProposalTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间未知"
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
}

function OutlineCompareDrawer({
  currentNodes,
  proposal,
  excludedNodeIds,
  onClose,
  onConfirm,
  applying,
}: {
  currentNodes: OutlineNode[]
  proposal: AIProposal
  excludedNodeIds: string[]
  onClose: () => void
  onConfirm: () => Promise<void>
  applying: boolean
}) {
  const proposed = Array.isArray(proposal.preview.nodes) ? proposal.preview.nodes as ProposalNode[] : []
  const currentById = new Map(currentNodes.map((node) => [node.node_id, node]))
  const currentPreview = proposed.map((item) => {
    const current = currentById.get(item.node_id ?? "")
    if (current) return { ...current, __action: "当前", __reason: "应用前的目录内容" } as ProposalNode
    return {
      node_id: item.node_id,
      title: "（当前目录中不存在）",
      level: item.level,
      target_word_count: null,
      __action: "新增",
      __reason: "该节点将在应用 AI 方案后出现",
    } as ProposalNode
  })
  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/25" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="flex h-full w-[min(900px,96vw)] flex-col border-l border-border bg-background shadow-2xl" role="dialog" aria-modal="true" aria-label="确认目录新版本">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div><h2 className="text-base font-semibold text-foreground">确认目录新版本</h2><p className="mt-1 text-xs text-muted-foreground">AI 方案尚未写入目录，请比较当前版本与新版本后再决定。</p></div>
          <Button size="icon" variant="ghost" onClick={onClose} aria-label="关闭版本对比"><span className="text-lg">×</span></Button>
        </div>
        <div className="grid min-h-0 flex-1 gap-3 overflow-hidden p-4 xl:grid-cols-2">
          <OutlineCompareColumn title="当前受影响内容" nodes={currentPreview} />
          <OutlineCompareColumn title="应用后目录内容" nodes={proposed.filter((item) => !excludedNodeIds.includes(item.node_id ?? ""))} highlighted />
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="outline" onClick={onClose}>暂不采用</Button>
          <Button variant="accent" onClick={() => void onConfirm()} loading={applying} icon={<Save className="h-4 w-4" />}>采用 AI 目录</Button>
        </div>
      </aside>
    </div>
  )
}

function OutlineCompareColumn({ title, nodes, highlighted = false }: { title: string; nodes: ProposalNode[]; highlighted?: boolean }) {
  return (
    <section className={cn("flex min-h-0 flex-col overflow-hidden rounded-[var(--radius)] border", highlighted ? "border-accent/40 bg-accent/[0.025]" : "border-border bg-card")}>
      <div className="border-b border-border px-3 py-2 text-xs font-semibold text-foreground">{title} <span className="ml-1 text-[10px] font-normal text-muted-foreground">{nodes.length} 项</span></div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {nodes.length ? <ul className="flex flex-col gap-1.5">{nodes.map((node, index) => <li key={`${node.node_id ?? "node"}-${index}`} className="rounded border border-border/70 px-2.5 py-2 text-xs"><div className="font-medium text-foreground">{node.title || node.node_id || "未命名节点"}</div><div className="mt-1 text-[10px] text-muted-foreground">{node.__action || "保持"}{node.__reason ? ` · ${node.__reason}` : ""}</div></li>)}</ul> : <p className="py-8 text-center text-xs text-muted-foreground">暂无可比较节点</p>}
      </div>
    </section>
  )
}

type ProposalNode = {
  __action?: string
  __reason?: string
  node_id?: string
  parent_id?: string | null
  title?: string
  level?: number
  enabled?: boolean
  target_word_count?: number | null
  source_rules?: string[]
  auto_fill?: string[]
  manual_fill?: string[]
  special_notes?: string[]
  reason?: string
}

type ProposalTreeNode = ProposalNode & { children: ProposalTreeNode[] }

function OutlineProposalPreview({ preview, excludedNodeIds, onToggle }: { preview: Record<string, unknown>; excludedNodeIds: string[]; onToggle: (nodeId: string) => void }) {
  const nodes = Array.isArray(preview.nodes) ? (preview.nodes as ProposalNode[]) : []
  if (!nodes.length) {
    return <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{String(preview.overall_reason || "本次没有识别到需要修改的目录节点，当前目录可以继续使用。")}</p>
  }
  const actionCounts = nodes.reduce<Record<string, number>>((acc, node) => {
    const key = node.__action || "change"
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const tree = buildProposalTree(nodes)
  const broadChange = nodes.length > 12 || (actionCounts.change ?? 0) > 8

  return (
    <div className="mt-2 flex max-h-72 flex-col gap-3 overflow-y-auto pr-1">
      {broadChange ? (
        <div className="rounded-[var(--radius)] border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
          该方案影响节点较多，可能是在重述完整目录而不是局部微调。建议先确认是否确实要整体重构；若只是局部修改，请忽略后用更具体的建议重新生成。
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {Object.entries(actionCounts).map(([action, count]) => (
          <span key={action} className="rounded-full bg-card px-2.5 py-1 text-[11px] text-muted-foreground">
            {proposalActionLabel(action)} {count}
          </span>
        ))}
        <span className="rounded-full bg-card px-2.5 py-1 text-[11px] text-muted-foreground">总计 {nodes.length} 个节点</span>
      </div>
      <ul className="flex flex-col gap-2">
        {tree.map((node) => (
            <ProposalNodeRow key={node.node_id || `${node.title}-${node.level}`} node={node} excludedNodeIds={excludedNodeIds} onToggle={onToggle} />
        ))}
      </ul>
    </div>
  )
}

function buildProposalTree(nodes: ProposalNode[]): ProposalTreeNode[] {
  const map = new Map<string, ProposalTreeNode>()
  nodes.forEach((node, index) => {
    const id = node.node_id || `proposal-node-${index}`
    map.set(id, { ...node, node_id: id, children: [] })
  })
  const roots: ProposalTreeNode[] = []
  map.forEach((node) => {
    const parent = node.parent_id ? map.get(node.parent_id) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  })
  const sortRec = (list: ProposalTreeNode[]) => {
    list.sort((a, b) => (a.level ?? 0) - (b.level ?? 0))
    list.forEach((item) => sortRec(item.children))
  }
  sortRec(roots)
  return roots
}

function ProposalNodeRow({ node, excludedNodeIds, onToggle }: { node: ProposalTreeNode; excludedNodeIds: string[]; onToggle: (nodeId: string) => void }) {
  const excluded = excludedNodeIds.includes(node.node_id ?? "")
  return (
    <li className={cn("rounded-[var(--radius)] border bg-card p-3", excluded ? "border-border opacity-50" : "border-primary/20")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <label className="mr-2 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground"><input type="checkbox" checked={!excluded} onChange={() => node.node_id && onToggle(node.node_id)} />采用</label>
          <p className="truncate text-xs font-semibold text-foreground">{node.title || "未命名节点"}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {proposalActionLabel(node.__action || "change")} · 层级 {node.level ?? "-"} · 字数 {node.target_word_count ?? "未设置"}
          </p>
        </div>
        {node.enabled === false ? <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">禁用</span> : null}
      </div>
      {node.reason || node.__reason ? <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{node.reason || node.__reason}</p> : null}
      <ProposalModuleSummary node={node} />
      {node.children.length ? (
        <ul className="mt-2 flex flex-col gap-2 border-l border-border pl-3">
          {node.children.map((child) => (
            <ProposalNodeRow key={child.node_id || `${child.title}-${child.level}`} node={child} excludedNodeIds={excludedNodeIds} onToggle={onToggle} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function ProposalModuleSummary({ node }: { node: ProposalNode }) {
  const modules = [
    ["主要来源", node.source_rules],
    ["自动补充", node.auto_fill],
    ["人工补充", node.manual_fill],
    ["特殊备注", node.special_notes],
  ] as const
  return (
    <div className="mt-2 grid gap-1.5 md:grid-cols-2">
      {modules.map(([label, items]) => {
        const first = items?.find(Boolean)
        if (!first) return null
        return (
          <div key={label} className="rounded bg-muted/45 px-2 py-1.5">
            <p className="text-[10px] font-medium text-muted-foreground">{label}</p>
            <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-foreground">{first}</p>
          </div>
        )
      })}
    </div>
  )
}

function proposalActionLabel(action: string): string {
  const labels: Record<string, string> = {
    create: "新增",
    update: "调整",
    delete: "删除",
    disable: "禁用",
    enable: "启用",
    change: "变更",
  }
  return labels[action] ?? action
}

function proposalIsBroad(preview: Record<string, unknown>): boolean {
  const nodes = Array.isArray(preview.nodes) ? preview.nodes as ProposalNode[] : []
  const changed = nodes.filter((node) => (node.__action || "change") !== "keep").length
  return nodes.length > 12 || changed > 12
}

function proposalHasChanges(preview: Record<string, unknown>): boolean {
  const nodes = Array.isArray(preview.nodes) ? preview.nodes as ProposalNode[] : []
  return nodes.some((node) => (node.__action || "change") !== "keep")
}
