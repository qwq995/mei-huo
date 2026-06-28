import { useMemo, useState } from "react"
import { ArrowRight, Calculator, ChevronRight, ListTree, Plus, RefreshCw, Save, Sparkles, Trash2, Wand2 } from "lucide-react"
import {
  applyOutlineProposal,
  createOutlineNode,
  deleteOutlineNode,
  estimateOutlineWordCounts,
  generateDirectory,
  listOutlineNodes,
  proposeOutlineAIPlan,
  proposePreGenerationOutlineRefine,
  rejectOutlineProposal,
  updateOutlineNode,
  type AIProposal,
  type OutlineNode,
  type ProjectResponse,
} from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, LoadingBlock, SectionTitle, TextArea, TextInput } from "@/components/ui"
import { cn } from "@/lib/utils"

type TreeNode = OutlineNode & { _children: TreeNode[] }
type RefineMode = "balanced" | "conservative" | "aggressive"

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
  const outline = useAsyncData<OutlineNode[]>(() => listOutlineNodes(project.project_id), [project.project_id])
  const [generating, setGenerating] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const tree = useMemo(() => buildTree(outline.data ?? []), [outline.data])
  const selected = useMemo(() => outline.data?.find((n) => n.node_id === selectedId) ?? null, [outline.data, selectedId])

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      await generateDirectory(project.project_id)
      toast.success("目录已生成")
      await outline.reload()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    } finally {
      setGenerating(false)
    }
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

  return (
    <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
      <Card className="flex flex-col p-5">
        <SectionTitle
          title="目录树"
          description="目录是后续逐章来源映射与正文生成的骨架。先生成，再精修、补字数和人工调整。"
          right={
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => outline.reload()} icon={<RefreshCw className="h-3.5 w-3.5" />}>
                刷新
              </Button>
              <Button size="sm" onClick={handleGenerate} loading={generating} icon={<Wand2 className="h-3.5 w-3.5" />}>
                {outline.data?.length ? "重新生成" : "生成目录"}
              </Button>
            </div>
          }
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
                <Button onClick={handleGenerate} loading={generating} icon={<Wand2 className="h-4 w-4" />}>
                  立即生成
                </Button>
              }
            />
          ) : (
            <>
              <div className="mb-3 flex items-center justify-between">
                <p className="text-xs text-muted-foreground">共 {outline.data.length} 个节点</p>
                <Button variant="outline" size="sm" onClick={handleEstimate} icon={<Calculator className="h-3.5 w-3.5" />}>
                  估算字数
                </Button>
              </div>
              <ul className="flex flex-col gap-1">
                {tree.map((node) => (
                  <OutlineRow key={node.node_id} node={node} selectedId={selectedId} onSelect={setSelectedId} />
                ))}
              </ul>
            </>
          )}
        </div>
      </Card>

      <div className="flex flex-col gap-5">
        <NodeEditor
          key={selected?.node_id ?? "none"}
          projectId={project.project_id}
          node={selected}
          nodeCount={outline.data?.length ?? 0}
          onSaved={() => outline.reload()}
          onDeleted={() => {
            setSelectedId(null)
            outline.reload()
          }}
          onCreated={(nodeId) => {
            setSelectedId(nodeId)
            outline.reload()
          }}
        />
        <AIOutlinePanel projectId={project.project_id} onApplied={() => outline.reload()} />
        <Card className="p-5">
          <p className="text-sm font-medium text-foreground">目录确认完成</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">确认结构、字数和四模块后进入章节工作台。父节点可作为容器，主要生成叶子节点。</p>
          <Button className="mt-4 w-full" onClick={onNext} icon={<ArrowRight className="h-4 w-4" />}>
            进入章节生成
          </Button>
        </Card>
      </div>
    </div>
  )
}

function OutlineRow({ node, selectedId, onSelect }: { node: TreeNode; selectedId: string | null; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(true)
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
          <span className={cn("truncate text-sm", disabled ? "text-muted-foreground/60 line-through" : "text-foreground")}>{node.title || "未命名章节"}</span>
          {node.target_word_count ? <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{node.target_word_count} 字</span> : null}
        </button>
      </div>
      {hasChildren && open ? (
        <ul className="flex flex-col gap-1">
          {node._children.map((child) => (
            <OutlineRow key={child.node_id} node={child} selectedId={selectedId} onSelect={onSelect} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function NodeEditor({
  projectId,
  node,
  nodeCount,
  onSaved,
  onDeleted,
  onCreated,
}: {
  projectId: string
  node: OutlineNode | null
  nodeCount: number
  onSaved: () => void
  onDeleted: () => void
  onCreated: (nodeId: string) => void
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
            <ModuleText label="[主要来源]" value={sourceRules} onChange={setSourceRules} />
            <ModuleText label="[自动补充]" value={autoFill} onChange={setAutoFill} />
            <ModuleText label="[人工补充需补充]" value={manualFill} onChange={setManualFill} />
            <ModuleText label="[特殊备注]" value={specialNotes} onChange={setSpecialNotes} rows={2} />
            <div className="flex items-center gap-2">
              <Button onClick={save} loading={saving} icon={<Save className="h-4 w-4" />} className="flex-1">
                保存修改
              </Button>
              <Button variant="danger" onClick={remove} loading={deleting} icon={<Trash2 className="h-4 w-4" />}>
                删除
              </Button>
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
      </div>
    </Card>
  )
}

function ModuleText({ label, value, onChange, rows = 3 }: { label: string; value: string; onChange: (v: string) => void; rows?: number }) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</label>
      <TextArea rows={rows} value={value} onChange={(e) => onChange(e.target.value)} placeholder="一行一条，可留空" />
    </div>
  )
}

function AIOutlinePanel({ projectId, onApplied }: { projectId: string; onApplied: () => void }) {
  const toast = useToast()
  const [suggestion, setSuggestion] = useState("")
  const [mode, setMode] = useState<RefineMode>("balanced")
  const [loading, setLoading] = useState(false)
  const [proposal, setProposal] = useState<AIProposal | null>(null)
  const [applying, setApplying] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  const proposeRefine = async () => {
    setLoading(true)
    setProposal(null)
    try {
      const result = await proposePreGenerationOutlineRefine(projectId, {
        mode,
        use_local_corpus: true,
        use_human_reference: false,
        project_type: "auto",
      })
      setProposal(result)
      toast.success("已生成目录精修建议，请确认后应用")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成精修建议失败")
    } finally {
      setLoading(false)
    }
  }

  const proposeCustom = async () => {
    if (!suggestion.trim()) {
      toast.error("请描述目录调整意图")
      return
    }
    setLoading(true)
    setProposal(null)
    try {
      const result = await proposeOutlineAIPlan(projectId, suggestion.trim())
      setProposal(result)
      toast.success("已生成调整方案，请确认后应用")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成方案失败")
    } finally {
      setLoading(false)
    }
  }

  const apply = async () => {
    if (!proposal) return
    setApplying(true)
    try {
      await applyOutlineProposal(projectId, proposal.id)
      toast.success("方案已应用")
      setProposal(null)
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
      setProposal(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "忽略建议失败")
    } finally {
      setRejecting(false)
    }
  }

  return (
    <Card className="p-5">
      <SectionTitle title="目录精修建议" description="AI 只创建待确认 proposal，不会直接覆盖目录。" />
      <div className="mt-4 flex flex-col gap-3">
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
        <Button onClick={proposeRefine} loading={loading} variant="accent" icon={<Sparkles className="h-4 w-4" />}>
          生成预生成目录精修建议
        </Button>
        <TextArea rows={3} value={suggestion} onChange={(e) => setSuggestion(e.target.value)} placeholder="也可以输入自然语言调整，例如：把注水、灌浆、覆盖封堵拆成工艺、参数控制、质量记录、安全环保几个子节。" />
        <Button onClick={proposeCustom} loading={loading} variant="outline" icon={<Wand2 className="h-4 w-4" />}>
          生成自定义调整方案
        </Button>
        {proposal ? (
          <div className="rounded-[var(--radius)] border border-accent/30 bg-accent/[0.05] p-3">
            <p className="text-xs font-medium text-accent">方案预览</p>
            <OutlineProposalPreview preview={proposal.preview} />
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button size="sm" variant="outline" onClick={reject} loading={rejecting}>
                忽略此方案
              </Button>
              <Button size="sm" onClick={apply} loading={applying}>
                确认并应用
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
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
}

type ProposalTreeNode = ProposalNode & { children: ProposalTreeNode[] }

function OutlineProposalPreview({ preview }: { preview: Record<string, unknown> }) {
  const nodes = Array.isArray(preview.nodes) ? (preview.nodes as ProposalNode[]) : []
  if (!nodes.length) {
    return <p className="mt-2 text-xs leading-relaxed text-muted-foreground">该方案没有返回可渲染的目录节点，请查看后端日志或重新生成建议。</p>
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
          <ProposalNodeRow key={node.node_id || `${node.title}-${node.level}`} node={node} />
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

function ProposalNodeRow({ node }: { node: ProposalTreeNode }) {
  return (
    <li className="rounded-[var(--radius)] border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-foreground">{node.title || "未命名节点"}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {proposalActionLabel(node.__action || "change")} · 层级 {node.level ?? "-"} · 字数 {node.target_word_count ?? "未设置"}
          </p>
        </div>
        {node.enabled === false ? <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">禁用</span> : null}
      </div>
      {node.__reason ? <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{node.__reason}</p> : null}
      <ProposalModuleSummary node={node} />
      {node.children.length ? (
        <ul className="mt-2 flex flex-col gap-2 border-l border-border pl-3">
          {node.children.map((child) => (
            <ProposalNodeRow key={child.node_id || `${child.title}-${child.level}`} node={child} />
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
