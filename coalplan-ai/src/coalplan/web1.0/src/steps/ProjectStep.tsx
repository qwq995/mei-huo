import { useState } from "react"
import { FileStack, FileText, FolderKanban, Layers, Plus, Search, Trash2 } from "lucide-react"
import { createProject, deleteProject, listProjects, listTemplates, recommendOutlineTemplates, type OutlineTemplateRecommendation, type ProjectResponse, type TemplateSummary } from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, ConfirmDialog, EmptyState, LoadingBlock, SectionTitle, TextInput } from "@/components/ui"
import { cn } from "@/lib/utils"

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
      setRecommendedCandidates(Object.fromEntries(result.candidates.map((item) => [item.template_id, item])))
      setSelectedOutlineTemplate(result.recommendations[0]?.template_id ?? null)
      toast.success(result.generated_by === "llm" ? "AI 已完成目录模板排序" : "已完成本地相关性排序")
    } catch (err) { toast.error(err instanceof Error ? err.message : "目录模板分析失败") }
    finally { setRecommending(false) }
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

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
      <Card className="p-5">
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
                    <div className={cn("group flex items-center gap-4 rounded-[var(--radius)] border p-3.5 transition-colors", selected ? "border-primary/40 bg-primary/[0.05]" : "border-border bg-card hover:bg-muted/40")}>
                      <button onClick={() => onSelect(p)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                        <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius)]", selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
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
                      <div className="flex items-center gap-2">
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

      <Card className="h-fit p-5">
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
            {recommendations.length ? <div className="mt-3 flex flex-col gap-2">{recommendations.map((item) => { const candidate = recommendedCandidates[item.template_id]; const selected = selectedOutlineTemplate === item.template_id; return <button key={item.template_id} onClick={() => setSelectedOutlineTemplate(item.template_id)} className={cn("rounded-[var(--radius)] border p-3 text-left", selected ? "border-primary/50 bg-primary/[0.06]" : "border-border bg-card hover:bg-muted/40")}><div className="flex items-start justify-between gap-3"><span className="text-sm font-medium">#{item.rank} {candidate?.file_name ?? item.template_id}</span><span className="text-xs font-semibold text-primary">{Math.round(item.score * 100)}%相关</span></div><div className="mt-1 text-xs text-muted-foreground">{item.match_reason}</div>{candidate ? <div className="mt-2 text-[11px] text-muted-foreground">{candidate.project_type} · {candidate.title_count}个目录标题 · {candidate.key_topics.slice(0, 4).join("、")}</div> : null}</button> })}</div> : null}
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">选择模板</label>
            {templates.loading ? (
              <div className="rounded-[var(--radius)] border border-border p-3 text-xs text-muted-foreground">正在加载模板...</div>
            ) : !templates.data?.length ? (
              <div className="rounded-[var(--radius)] border border-dashed border-border p-3 text-xs text-muted-foreground">暂无可用模板</div>
            ) : (
              <div className="flex max-h-72 flex-col gap-2 overflow-y-auto pr-1">
                {templates.data.map((t) => {
                  const checked = (templateId || templates.data?.[0]?.template_id) === t.template_id
                  return (
                    <button
                      key={t.template_id}
                      onClick={() => setTemplateId(t.template_id)}
                      className={cn("flex items-center gap-3 rounded-[var(--radius)] border p-3 text-left transition-colors", checked ? "border-primary/40 bg-primary/[0.05]" : "border-border hover:bg-muted/40")}
                    >
                      <span className={cn("flex h-4 w-4 items-center justify-center rounded-full border", checked ? "border-primary" : "border-muted-foreground/50")}>
                        {checked ? <span className="h-2 w-2 rounded-full bg-primary" /> : null}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-foreground">{t.name}</span>
                        {t.path ? <span className="block truncate text-xs text-muted-foreground">{t.path}</span> : null}
                      </span>
                    </button>
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
    </div>
  )
}
