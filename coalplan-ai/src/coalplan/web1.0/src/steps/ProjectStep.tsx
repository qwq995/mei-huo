import { useEffect, useRef, useState } from "react"
import { ChevronRight, Eye, FileStack, FileText, FolderKanban, Layers, Loader2, Pencil, Plus, Search, Trash2, Upload, X } from "lucide-react"
import { createProject, deleteOutlineTemplate, deleteProject, getOutlineTemplate, getTemplateTree, importOutlineTemplates, listOutlineTemplates, listProjects, listTemplates, recommendOutlineTemplates, updateOutlineTemplate, updateProjectMetadata, type OutlineTemplateDocument, type OutlineTemplateNode, type OutlineTemplateRecommendation, type OutlineTemplateSummary, type ProjectResponse, type TemplateNode, type TemplateSummary } from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, ConfirmDialog, EmptyState, LoadingBlock, SectionTitle, TextInput } from "@/components/ui"
import { cn } from "@/lib/utils"

const TEMPLATE_RECOMMENDATION_DRAFT_KEY = "coalplan.template-recommendation-draft"

type TemplateRecommendationDraft = {
  name: string
  tagsText: string
  recommendations: OutlineTemplateRecommendation[]
  candidates: Record<string, { file_name: string; project_type: string; key_topics: string[]; title_count: number }>
  selectedTemplateId: string | null
}

function countTemplateNodes(nodes: TemplateNode[]): number {
  return nodes.reduce((count, node) => count + 1 + countTemplateNodes(node.children ?? []), 0)
}

function outlineNodesToTree(nodes: OutlineTemplateNode[]): TemplateNode[] {
  const byParent = new Map<string | null, TemplateNode[]>()
  const mapped = new Map<string, TemplateNode>()
  for (const node of nodes) mapped.set(node.node_id, { id: node.node_id, title: node.title, level: node.level, source_rules: [], auto_fill: [], manual_fill: [], special_notes: [], children: [] })
  for (const node of nodes) {
    const item = mapped.get(node.node_id)!
    const parent = node.parent_id ?? null
    if (!byParent.has(parent)) byParent.set(parent, [])
    byParent.get(parent)!.push(item)
    if (parent && mapped.has(parent)) mapped.get(parent)!.children.push(item)
  }
  for (const items of byParent.values()) items.sort((a, b) => (nodes.find((node) => node.node_id === a.id)?.order ?? 0) - (nodes.find((node) => node.node_id === b.id)?.order ?? 0))
  return byParent.get(null) ?? []
}

function TemplateTree({ nodes, depth = 0 }: { nodes: TemplateNode[]; depth?: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      {nodes.map((node) => (
        <div key={node.id}>
          <div
            className="flex min-h-9 items-center gap-2 rounded-[var(--radius)] px-2.5 py-1.5 text-sm hover:bg-muted/60"
            style={{ paddingLeft: `${10 + depth * 22}px` }}
          >
            {node.children?.length ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <span className="ml-0.5 h-3.5 w-3.5 shrink-0" />}
            <span className="min-w-0 flex-1 text-foreground">{node.title || "未命名节点"}</span>
            {node.target_word_count ? <span className="shrink-0 text-[11px] text-muted-foreground">{node.target_word_count}字</span> : null}
          </div>
          {node.children?.length ? <TemplateTree nodes={node.children} depth={depth + 1} /> : null}
        </div>
      ))}
    </div>
  )
}

function TemplateDetailDialog({
  template,
  nodes,
  loading,
  error,
  onClose,
}: {
  template: TemplateSummary
  nodes: TemplateNode[]
  loading: boolean
  error: string | null
  onClose: () => void
}) {
  const total = countTemplateNodes(nodes)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/35 p-4 backdrop-blur-sm" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section role="dialog" aria-modal="true" aria-labelledby="template-detail-title" className="flex max-h-[min(82vh,760px)] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius)] border border-border bg-card shadow-2xl">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="template-detail-title" className="truncate text-base font-semibold text-foreground">{template.name}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>模板目录详情</span>
              {loading ? <span>正在读取...</span> : <span>{total} 个目录节点</span>}
            </div>
            {template.path ? <p className="mt-1 truncate text-[11px] text-muted-foreground" title={template.path}>{template.path}</p> : null}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭目录详情" title="关闭">
            <X className="h-4 w-4" />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {loading ? (
            <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在加载模板目录</div>
          ) : error ? (
            <div className="rounded-[var(--radius)] border border-[var(--color-danger)]/25 bg-[var(--color-danger)]/[0.04] p-4 text-sm text-[var(--color-danger)]">目录读取失败：{error}</div>
          ) : !nodes.length ? (
            <div className="rounded-[var(--radius)] border border-dashed border-border p-8 text-center text-sm text-muted-foreground">该模板暂未解析出目录节点</div>
          ) : (
            <TemplateTree nodes={nodes} />
          )}
        </div>
        <footer className="flex shrink-0 justify-end border-t border-border px-5 py-3">
          <Button variant="outline" size="sm" onClick={onClose}>返回模板选择</Button>
        </footer>
      </section>
    </div>
  )
}

export function ProjectStep({
  current,
  onSelect,
}: {
  current: ProjectResponse | null
  onSelect: (p: ProjectResponse | null) => void
}) {
  const toast = useToast()
  const projects = useAsyncData<ProjectResponse[]>(() => listProjects(), [])
  const templates = useAsyncData<TemplateSummary[]>(() => listTemplates(), [])
  const outlineTemplates = useAsyncData<OutlineTemplateSummary[]>(() => listOutlineTemplates(), [])
  const [name, setName] = useState("")
  const [templateId, setTemplateId] = useState("")
  const [tagsText, setTagsText] = useState("")
  const [recommendations, setRecommendations] = useState<OutlineTemplateRecommendation[]>([])
  const [recommendedCandidates, setRecommendedCandidates] = useState<Record<string, { file_name: string; project_type: string; key_topics: string[]; title_count: number }>>({})
  const [selectedOutlineTemplate, setSelectedOutlineTemplate] = useState<string | null>(null)
  const [recommending, setRecommending] = useState(false)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ProjectResponse | null>(null)
  const [currentName, setCurrentName] = useState("")
  const [currentTags, setCurrentTags] = useState("")
  const [savingMetadata, setSavingMetadata] = useState(false)
  const [templateSearch, setTemplateSearch] = useState("")
  const [templateType, setTemplateType] = useState("all")
  const [templateManagerOpen, setTemplateManagerOpen] = useState(false)
  const [templateImporting, setTemplateImporting] = useState(false)
  const templateFileInput = useRef<HTMLInputElement>(null)
  const [templateDetailId, setTemplateDetailId] = useState<string | null>(null)
  const [templateDetailNodes, setTemplateDetailNodes] = useState<TemplateNode[]>([])
  const [templateDetailTemplate, setTemplateDetailTemplate] = useState<TemplateSummary | null>(null)
  const [templateDetailLoading, setTemplateDetailLoading] = useState(false)
  const [templateDetailError, setTemplateDetailError] = useState<string | null>(null)

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(TEMPLATE_RECOMMENDATION_DRAFT_KEY)
      if (!raw) return
      const draft = JSON.parse(raw) as Partial<TemplateRecommendationDraft>
      if (typeof draft.name !== "string" || typeof draft.tagsText !== "string" || !Array.isArray(draft.recommendations)) return
      setName(draft.name)
      setTagsText(draft.tagsText)
      setRecommendations(draft.recommendations)
      setRecommendedCandidates(draft.candidates ?? {})
      setSelectedOutlineTemplate(draft.selectedTemplateId ?? null)
    } catch {
      window.localStorage.removeItem(TEMPLATE_RECOMMENDATION_DRAFT_KEY)
    }
  }, [])

  useEffect(() => {
    setCurrentName(current?.name ?? "")
    setCurrentTags((current?.project_tags ?? []).join("、"))
  }, [current])

  const handleSaveMetadata = async () => {
    if (!current) return
    if (!currentName.trim()) { toast.error("项目名称不能为空"); return }
    setSavingMetadata(true)
    try {
      const updated = await updateProjectMetadata(current.project_id, { name: currentName.trim(), project_tags: currentTags.split(/[,，、\s]+/).map((item) => item.trim()).filter(Boolean) })
      onSelect(updated)
      await projects.reload()
      toast.success("项目名称和标签已保存")
    } catch (err) { toast.error(err instanceof Error ? err.message : "保存项目资料失败") }
    finally { setSavingMetadata(false) }
  }

  const handleCreate = async () => {
    if (!name.trim()) {
      toast.error("请填写项目名称")
      return
    }
    const tpl = templateId || templates.data?.[0]?.template_id
    if (!tpl) {
      toast.error("请先选择一个模板")
      return
    }
    setCreating(true)
    try {
      const project = await createProject(name.trim(), tpl, tagsText.split(/[,，、\s]+/).filter(Boolean), selectedOutlineTemplate)
      toast.success("项目已创建")
      setName("")
      setTagsText("")
      setRecommendations([])
      setSelectedOutlineTemplate(null)
      window.localStorage.removeItem(TEMPLATE_RECOMMENDATION_DRAFT_KEY)
      await projects.reload()
      onSelect(project)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  const handleRecommend = async () => {
    if (!name.trim()) { toast.error("先填写项目名称，再分析目录模板"); return }
    setRecommending(true)
    try {
      const result = await recommendOutlineTemplates(name.trim(), tagsText.split(/[,，、\s]+/).filter(Boolean))
      setRecommendations(result.recommendations)
      const candidates = Object.fromEntries(result.candidates.map((item) => [item.template_id, item]))
      const nextSelectedTemplate = result.recommendations[0]?.template_id ?? null
      setRecommendedCandidates(candidates)
      setSelectedOutlineTemplate(nextSelectedTemplate)
      try {
        window.localStorage.setItem(TEMPLATE_RECOMMENDATION_DRAFT_KEY, JSON.stringify({
          name: name.trim(),
          tagsText,
          recommendations: result.recommendations,
          candidates,
          selectedTemplateId: nextSelectedTemplate,
        } satisfies TemplateRecommendationDraft))
      } catch {
        // Recommendation results remain usable when browser storage is unavailable.
      }
      toast.success(result.generated_by === "llm" ? "AI 已完成目录模板排序" : "已完成本地相关性排序")
    } catch (err) { toast.error(err instanceof Error ? err.message : "目录模板分析失败") }
    finally { setRecommending(false) }
  }

  const handleViewTemplate = async (template: TemplateSummary, source: "base" | "outline" = "base") => {
    setTemplateDetailId(template.template_id)
    setTemplateDetailTemplate(template)
    setTemplateDetailNodes([])
    setTemplateDetailError(null)
    setTemplateDetailLoading(true)
    try {
      if (source === "outline") {
        const document: OutlineTemplateDocument = await getOutlineTemplate(template.template_id)
        setTemplateDetailTemplate({ template_id: document.template_id, name: document.file_name, path: document.source_path })
        setTemplateDetailNodes(outlineNodesToTree(document.nodes))
      } else {
        setTemplateDetailNodes(await getTemplateTree(template.template_id))
      }
    } catch (err) {
      setTemplateDetailError(err instanceof Error ? err.message : "无法读取模板目录")
    } finally {
      setTemplateDetailLoading(false)
    }
  }

  const handleSelectRecommendedTemplate = (templateId: string) => {
    setSelectedOutlineTemplate(templateId)
    try {
      const raw = window.localStorage.getItem(TEMPLATE_RECOMMENDATION_DRAFT_KEY)
      if (!raw) return
      const draft = JSON.parse(raw) as TemplateRecommendationDraft
      window.localStorage.setItem(TEMPLATE_RECOMMENDATION_DRAFT_KEY, JSON.stringify({ ...draft, selectedTemplateId: templateId }))
    } catch {
      // Selection remains active in memory when browser storage is unavailable.
    }
  }

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await deleteProject(id)
      toast.success("项目已删除")
      if (current?.project_id === id) onSelect(null)
      await projects.reload()
      setDeleteTarget(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeletingId(null)
    }
  }

  const templateTypes = Array.from(new Set((outlineTemplates.data ?? []).map((item) => item.project_type).filter(Boolean))).sort()
  const normalizedTemplateSearch = templateSearch.trim().toLowerCase()
  const filteredOutlineTemplates = (outlineTemplates.data ?? []).filter((item) => {
    const haystack = [item.file_name, item.project_name, item.project_type, ...item.tags, ...item.key_topics, ...item.top_headings].join(" ").toLowerCase()
    return (!normalizedTemplateSearch || haystack.includes(normalizedTemplateSearch)) && (templateType === "all" || item.project_type === templateType)
  })

  const handleImportTemplates = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ""
    if (!files.length) return
    setTemplateImporting(true)
    try {
      const documents: OutlineTemplateDocument[] = []
      const failures: string[] = []
      for (const file of files) {
        try {
          const value = JSON.parse(await file.text())
          const items = Array.isArray(value) ? value : Array.isArray(value.templates) ? value.templates : [value]
          documents.push(...items)
        } catch {
          failures.push(`${file.name} 格式无效`)
        }
      }
      if (!documents.length) throw new Error(failures.join("；") || "没有可导入的模板")
      const result = await importOutlineTemplates(documents)
      await outlineTemplates.reload()
      toast.success(`已导入 ${result.imported_count} 个模板${result.failed_count ? `，${result.failed_count} 个失败` : ""}${failures.length ? `；${failures.join("；")}` : ""}`)
    } catch (err) { toast.error(err instanceof Error ? err.message : "模板导入失败") }
    finally { setTemplateImporting(false) }
  }

  const handleEditTemplate = async (item: OutlineTemplateSummary) => {
    const fileName = window.prompt("模板名称", item.file_name)
    if (fileName === null || !fileName.trim()) return
    const projectType = window.prompt("项目类型", item.project_type)
    if (projectType === null) return
    try {
      await updateOutlineTemplate(item.template_id, { file_name: fileName.trim(), project_type: projectType.trim() })
      await outlineTemplates.reload()
      toast.success("模板信息已更新")
    } catch (err) { toast.error(err instanceof Error ? err.message : "模板更新失败") }
  }

  const handleDeleteTemplate = async (item: OutlineTemplateSummary) => {
    if (!window.confirm(`确定删除“${item.file_name}”吗？删除后将从模板索引和目录库中移除。`)) return
    try {
      await deleteOutlineTemplate(item.template_id)
      if (selectedOutlineTemplate === item.template_id) setSelectedOutlineTemplate(null)
      await outlineTemplates.reload()
      toast.success("模板已删除")
    } catch (err) { toast.error(err instanceof Error ? err.message : "模板删除失败") }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] xl:gap-6">
      <Card className="min-w-0 p-4 sm:p-5">
        <SectionTitle
          title="工程项目"
          description="打开已有项目，或从模板新建一个可持久化的生成工作区。"
          right={
            <Button variant="ghost" size="sm" onClick={() => projects.reload()}>
              刷新
            </Button>
          }
        />
        <div className="mt-4">
          {projects.loading ? (
            <LoadingBlock />
          ) : projects.error ? (
            <EmptyState icon={<FolderKanban className="h-7 w-7" />} title="无法连接后端服务" description={projects.error} />
          ) : !projects.data?.length ? (
            <EmptyState icon={<FolderKanban className="h-7 w-7" />} title="还没有项目" description="使用右侧表单创建第一个施工组织设计项目。" />
          ) : (
            <ul className="flex flex-col gap-2.5">
              {projects.data.map((p) => {
                const selected = current?.project_id === p.project_id
                return (
                  <li key={p.project_id}>
                    <div className={cn("group flex items-center gap-3 rounded-[var(--radius)] border p-3 transition-colors sm:gap-4 sm:p-3.5", selected ? "border-primary/40 bg-primary/[0.05]" : "border-border bg-card hover:bg-muted/40")}>
                      <button onClick={() => onSelect(p)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius)] sm:h-10 sm:w-10", selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
                          <FolderKanban className="h-5 w-5" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-foreground">{p.name}</span>
                          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                            <span className="inline-flex items-center gap-1">
                              <FileText className="h-3 w-3" />
                              资料 {p.source_document_count}
                            </span>
                            <span className="inline-flex items-center gap-1">
                              <Layers className="h-3 w-3" />
                              切章 {p.section_count}
                            </span>
                            <span className="inline-flex items-center gap-1">
                              <FileStack className="h-3 w-3" />
                              运行 {p.run_count}
                            </span>
                          </span>
                        </span>
                      </button>
                      <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
                        {selected ? (
                          <span className="rounded-full bg-accent/15 px-2.5 py-0.5 text-xs font-medium text-accent">当前</span>
                        ) : (
                          <Button variant="outline" size="sm" onClick={() => onSelect(p)}>
                            选择
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          loading={deletingId === p.project_id}
                          onClick={() => setDeleteTarget(p)}
                          aria-label="删除项目"
                          className="text-muted-foreground hover:text-[var(--color-danger)]"
                        >
                          {deletingId === p.project_id ? null : <Trash2 className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </Card>

      <div className="flex min-w-0 flex-col gap-4">
      {current ? <Card className="min-w-0 h-fit p-4 sm:p-5">
        <SectionTitle title="当前项目资料" description="名称和标签会保存到项目数据库，后续生成与目录推荐会继续使用。" />
        <div className="mt-4 flex flex-col gap-3">
          <div><label className="mb-1.5 block text-xs font-medium text-muted-foreground">项目名称</label><TextInput value={currentName} onChange={(e) => setCurrentName(e.target.value)} /></div>
          <div><label className="mb-1.5 block text-xs font-medium text-muted-foreground">项目标签</label><TextInput value={currentTags} onChange={(e) => setCurrentTags(e.target.value)} placeholder="用空格或逗号分隔" /></div>
          <Button onClick={() => void handleSaveMetadata()} loading={savingMetadata} icon={<FileStack className="h-4 w-4" />}>保存项目资料</Button>
        </div>
      </Card> : null}
      <Card className="min-w-0 h-fit p-4 sm:p-5">
        <SectionTitle title="新建项目" description="模板只控制结构，项目事实仍来自上传的投标文档和人工补充。" />
        <div className="mt-4 flex flex-col gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">项目名称</label>
            <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：宁夏煤火治理施工组织设计" onKeyDown={(e) => e.key === "Enter" && handleCreate()} />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">项目标签</label>
            <TextInput value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="例如：抽水蓄能、隧洞、大坝（用空格或逗号分隔）" />
          </div>
          <div className="rounded-[var(--radius)] border border-dashed border-primary/30 bg-primary/[0.03] p-3">
            <div className="flex items-center justify-between gap-3"><div><div className="text-sm font-medium">先找一个合适的目录参考</div><div className="mt-1 text-xs text-muted-foreground">AI 只比较目录结构，不会把参考项目事实带入新项目。</div></div><Button variant="outline" size="sm" loading={recommending} icon={<Search className="h-3.5 w-3.5" />} onClick={handleRecommend}>分析模板</Button></div>
            {recommendations.length ? <div className="mt-3 flex flex-col gap-2">{recommendations.map((item) => {
              const candidate = recommendedCandidates[item.template_id]
              const selected = selectedOutlineTemplate === item.template_id
              const template = templates.data?.find((entry) => entry.template_id === item.template_id)
              return <div key={item.template_id} className={cn("rounded-[var(--radius)] border p-3", selected ? "border-primary/50 bg-primary/[0.06]" : "border-border bg-card") }>
                <div className="flex items-start gap-3">
                  <button onClick={() => handleSelectRecommendedTemplate(item.template_id)} className="min-w-0 flex-1 text-left">
                    <div className="flex items-start justify-between gap-3"><span className="text-sm font-medium">#{item.rank} {candidate?.file_name ?? item.template_id}</span><span className="shrink-0 text-xs font-semibold text-primary">{Math.round(item.score * 100)}%相关</span></div>
                    <div className="mt-1 text-xs text-muted-foreground">{item.match_reason}</div>
                    {candidate ? <div className="mt-2 text-[11px] text-muted-foreground">{candidate.project_type} · {candidate.title_count}个目录标题 · {candidate.key_topics.slice(0, 4).join("、")}</div> : null}
                  </button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleViewTemplate(template ?? { template_id: item.template_id, name: candidate?.file_name ?? item.template_id }, template ? "base" : "outline")}
                    icon={<Eye className="h-3.5 w-3.5" />}
                    aria-label={`查看${candidate?.file_name ?? item.template_id}目录`}
                  >查看目录</Button>
                </div>
              </div>
            })}</div> : null}
          </div>
          <div className="flex items-center justify-between gap-3 rounded-[var(--radius)] border border-border bg-muted/[0.18] p-3">
            <div><div className="text-sm font-medium text-foreground">目录模板库</div><div className="mt-1 text-xs text-muted-foreground">已收录 {outlineTemplates.data?.length ?? 0} 个参考模板，可搜索、查看、选用或管理。</div></div>
            <Button variant="outline" size="sm" onClick={() => setTemplateManagerOpen(true)} icon={<FolderKanban className="h-3.5 w-3.5" />}>模板管理</Button>
          </div>
          {templateManagerOpen ? <div className="fixed inset-0 z-40 flex items-center justify-center bg-foreground/35 p-4 backdrop-blur-sm" onMouseDown={(event) => event.target === event.currentTarget && setTemplateManagerOpen(false)}>
          <div className="flex max-h-[min(88vh,820px)] w-full max-w-4xl flex-col overflow-hidden rounded-[var(--radius)] border border-border bg-card shadow-2xl">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-5 py-4">
              <div>
                <div className="text-base font-semibold text-foreground">目录模板管理</div>
                <div className="mt-1 text-xs text-muted-foreground">搜索并查看模板目录，手动选用参考模板，或批量导入标准 JSON。</div>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setTemplateManagerOpen(false)} aria-label="关闭模板管理"><X className="h-4 w-4" /></Button>
            </div>
            <div className="shrink-0 border-b border-border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-muted-foreground">当前显示 {filteredOutlineTemplates.length} / {outlineTemplates.data?.length ?? 0}</span><Button variant="outline" size="sm" loading={templateImporting} icon={<Upload className="h-3.5 w-3.5" />} onClick={() => templateFileInput.current?.click()}>批量导入 JSON</Button><input ref={templateFileInput} type="file" accept=".json,application/json" multiple className="hidden" onChange={(event) => void handleImportTemplates(event)} /></div>
              <details className="mt-3 rounded-[var(--radius)] border border-dashed border-border bg-muted/[0.16] px-3 py-2">
                <summary className="cursor-pointer text-xs font-medium text-foreground">查看 JSON 结构说明</summary>
                <div className="mt-2 grid gap-3 text-[11px] text-muted-foreground lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <pre className="overflow-x-auto rounded-[var(--radius)] bg-foreground/[0.04] p-3 leading-5">{`{
  "template_id": "my_template",
  "file_name": "水电项目目录参考.json",
  "project_name": "示例项目",
  "project_type": "水电",
  "tags": ["隧洞", "灌浆"],
  "key_topics": ["施工部署"],
  "nodes": [
    { "node_id": "n1", "title": "工程概况", "level": 1,
      "parent_id": null, "order": 0, "source_line": 1,
      "source_path": ["工程概况"], "topic_keys": ["概况"],
      "is_leaf": true }
  ]
}`}</pre>
                  <div className="space-y-1.5"><p><b className="text-foreground">必填</b>：<code>template_id</code>、<code>file_name</code>、<code>project_name</code>、<code>project_type</code>、<code>nodes</code>。</p><p><b className="text-foreground">节点关系</b>：顶层节点的 <code>parent_id</code> 为 <code>null</code>，子节点填写父节点的 <code>node_id</code>。</p><p><b className="text-foreground">批量格式</b>：可以上传多个 JSON 文件；单文件也可以是单个模板对象，或包含 <code>templates</code> 数组的对象。</p><p><b className="text-foreground">更新规则</b>：相同 <code>template_id</code> 会更新原模板并同步索引；删除会同时移除索引、JSON 和 Markdown 文件。</p></div>
                </div>
              </details>
              <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_170px]">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <TextInput value={templateSearch} onChange={(event) => setTemplateSearch(event.target.value)} className="pl-9" placeholder="搜索名称、项目、标签、工艺或目录标题" aria-label="搜索全部目录模板" />
              </div>
              <select value={templateType} onChange={(event) => setTemplateType(event.target.value)} className="h-10 rounded-[var(--radius)] border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="按项目类型筛选">
                <option value="all">全部项目类型</option>
                {templateTypes.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </div>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4 pr-3">
              {outlineTemplates.loading ? <div className="flex items-center justify-center gap-2 p-6 text-xs text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在加载全部模板</div> : outlineTemplates.error ? <div className="rounded-[var(--radius)] border border-dashed border-border p-4 text-xs text-muted-foreground">模板索引加载失败：{outlineTemplates.error}</div> : !filteredOutlineTemplates.length ? <div className="rounded-[var(--radius)] border border-dashed border-border p-6 text-center text-xs text-muted-foreground">没有匹配的目录模板</div> : filteredOutlineTemplates.map((item) => {
                const selected = selectedOutlineTemplate === item.template_id
                return <div key={item.template_id} className={cn("rounded-[var(--radius)] border bg-card p-3", selected ? "border-primary/50 ring-1 ring-primary/15" : "border-border")}>
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-foreground" title={item.file_name}>{item.file_name}</div>
                      <div className="mt-1 truncate text-xs text-muted-foreground" title={item.project_name}>{item.project_name || "未标注项目"}</div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{item.project_type || "未分类"}</span>
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{item.title_count} 个标题</span>
                        {item.tags.slice(0, 3).map((tag) => <span key={tag} className="rounded-full bg-primary/[0.08] px-2 py-0.5 text-[11px] text-primary">{tag}</span>)}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col gap-1.5 sm:flex-row">
                      <Button variant={selected ? "primary" : "outline"} size="sm" onClick={() => setSelectedOutlineTemplate(item.template_id)}>{selected ? "已选用" : "手动选用"}</Button>
                      <Button variant="ghost" size="sm" onClick={() => void handleViewTemplate({ template_id: item.template_id, name: item.file_name, path: item.source_path }, "outline")} icon={<Eye className="h-3.5 w-3.5" />}>查看目录</Button>
                      <Button variant="ghost" size="icon" onClick={() => void handleEditTemplate(item)} aria-label={`编辑${item.file_name}`} title="编辑模板信息"><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="icon" onClick={() => void handleDeleteTemplate(item)} aria-label={`删除${item.file_name}`} title="删除模板" className="text-muted-foreground hover:text-[var(--color-danger)]"><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  </div>
                  {item.key_topics.length ? <div className="mt-2 truncate text-[11px] text-muted-foreground" title={item.key_topics.join("、")}>主题：{item.key_topics.slice(0, 6).join("、")}</div> : null}
                </div>
              })}
            </div>
          </div>
          </div> : null}
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <label className="block text-xs font-medium text-muted-foreground">选择模板</label>
              <span className="text-[11px] text-muted-foreground">可先查看目录，再决定是否选用</span>
            </div>
            {templates.loading ? (
              <div className="rounded-[var(--radius)] border border-border p-3 text-xs text-muted-foreground">正在加载模板...</div>
            ) : !templates.data?.length ? (
              <div className="rounded-[var(--radius)] border border-dashed border-border p-3 text-xs text-muted-foreground">暂无可用模板</div>
            ) : (
              <div className="flex max-h-56 flex-col gap-2 overflow-y-auto pr-1 sm:max-h-72">
                {templates.data.map((t) => {
                  const checked = (templateId || templates.data?.[0]?.template_id) === t.template_id
                  return (
                    <div
                      key={t.template_id}
                      className={cn("flex items-center gap-2 rounded-[var(--radius)] border p-2.5 transition-colors", checked ? "border-primary/40 bg-primary/[0.05]" : "border-border hover:bg-muted/40")}
                    >
                      <button onClick={() => setTemplateId(t.template_id)} className="flex min-w-0 flex-1 items-center gap-3 rounded-[var(--radius)] p-1 text-left">
                        <span className={cn("flex h-4 w-4 items-center justify-center rounded-full border", checked ? "border-primary" : "border-muted-foreground/50")}>
                          {checked ? <span className="h-2 w-2 rounded-full bg-primary" /> : null}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-foreground">{t.name}</span>
                          {t.path ? <span className="block truncate text-xs text-muted-foreground">{t.path}</span> : null}
                        </span>
                      </button>
                      <Button variant="outline" size="sm" onClick={() => void handleViewTemplate(t)} icon={<Eye className="h-3.5 w-3.5" />} aria-label={`查看${t.name}目录`}>
                        查看目录
                      </Button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
          <Button onClick={handleCreate} loading={creating} icon={<Plus className="h-4 w-4" />}>
            创建项目
          </Button>
        </div>
      </Card>
      </div>
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除工程项目"
        description={`将删除“${deleteTarget?.name ?? ""}”及其资料索引、目录、章节版本和生成记录，此操作无法撤销。`}
        confirmLabel="确认删除"
        danger
        loading={Boolean(deletingId)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && void handleDelete(deleteTarget.project_id)}
      />
      {templateDetailId ? (() => {
        const detailTemplate = templates.data?.find((item) => item.template_id === templateDetailId)
        return templateDetailTemplate ?? detailTemplate ? <TemplateDetailDialog template={templateDetailTemplate ?? detailTemplate!} nodes={templateDetailNodes} loading={templateDetailLoading} error={templateDetailError} onClose={() => { setTemplateDetailId(null); setTemplateDetailTemplate(null) }} /> : null
      })() : null}
    </div>
  )
}
