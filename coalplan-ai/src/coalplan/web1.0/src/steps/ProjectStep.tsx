import { useState } from "react"
import { FileStack, FileText, FolderKanban, Layers, Plus, Trash2 } from "lucide-react"
import { createProject, deleteProject, listProjects, listTemplates, type ProjectResponse, type TemplateSummary } from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, LoadingBlock, SectionTitle, TextInput } from "@/components/ui"
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
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

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
      const project = await createProject(name.trim(), tpl)
      toast.success("项目已创建")
      setName("")
      await projects.reload()
      onSelect(project)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await deleteProject(id)
      toast.success("项目已删除")
      if (current?.project_id === id) onSelect(null)
      await projects.reload()
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
                          onClick={() => handleDelete(p.project_id)}
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
    </div>
  )
}
