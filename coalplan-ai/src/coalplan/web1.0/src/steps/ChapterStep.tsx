import { useMemo, useState } from "react"
import { ArrowRight, CheckCircle2, ChevronRight, FileEdit, FileText, GitBranch, History, Pencil, Save, Sparkles, Wand2, X } from "lucide-react"
import {
  applyChapterProposal,
  createManualVersion,
  generateChapter,
  generateChildChapters,
  getChapter,
  getSourceSection,
  listOutlineNodes,
  listVersions,
  proposeChapterEdit,
  rejectChapterProposal,
  selectVersion,
  type ChapterResponse,
  type SourceSection,
  type ChapterVersion,
  type OutlineNode,
  type ProjectResponse,
} from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, LoadingBlock, SectionTitle, StatusBadge, TextArea } from "@/components/ui"
import { Markdown } from "@/components/Markdown"
import { AttachmentPanel } from "@/steps/AttachmentPanel"
import { cn, formatDateTime } from "@/lib/utils"

function getRenderableNodes(nodes: OutlineNode[]): OutlineNode[] {
  const parentIds = new Set(nodes.map((n) => n.parent_id).filter(Boolean) as string[])
  const leaves = nodes.filter((n) => n.enabled !== false && !parentIds.has(n.node_id))
  return leaves.length ? leaves : nodes.filter((n) => n.enabled !== false)
}

export function ChapterStep({ project, onNext }: { project: ProjectResponse; onNext: () => void }) {
  const outline = useAsyncData<OutlineNode[]>(() => listOutlineNodes(project.project_id), [project.project_id])
  const [activeNode, setActiveNode] = useState<OutlineNode | null>(null)
  const nodes = useMemo(() => getRenderableNodes(outline.data ?? []), [outline.data])

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <Card className="flex max-h-[calc(100vh-140px)] flex-col p-4 lg:sticky lg:top-20">
        <SectionTitle title="待生成章节" right={<span className="text-xs text-muted-foreground">{nodes.length}</span>} />
        <div className="mt-3 flex-1 overflow-y-auto">
          {outline.loading ? (
            <LoadingBlock />
          ) : !nodes.length ? (
            <EmptyState icon={<FileEdit className="h-6 w-6" />} title="暂无章节" description="请先在上一步生成并确认目录。" />
          ) : (
            <ul className="flex flex-col gap-1">
              {nodes.map((node) => {
                const isActive = activeNode?.node_id === node.node_id
                return (
                  <li key={node.node_id}>
                    <button
                      onClick={() => setActiveNode(node)}
                      className={cn("flex w-full items-center gap-2 rounded-[var(--radius)] px-2.5 py-2 text-left text-sm transition-colors", isActive ? "bg-primary/[0.06] text-primary" : "text-foreground hover:bg-muted/60")}
                      style={{ paddingLeft: 10 + ((node.level ?? 1) - 1) * 10 }}
                    >
                      <span className="min-w-0 flex-1 truncate">{node.title || "未命名章节"}</span>
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
          <ChapterWorkspace key={activeNode.node_id} project={project} node={activeNode} />
        ) : (
          <Card className="p-5">
            <EmptyState icon={<FileEdit className="h-8 w-8" />} title="选择章节开始撰写" description="左侧选择一个叶子章节，然后补充材料、生成正文、审阅版本。" />
          </Card>
        )}
      </div>
    </div>
  )
}

function ChapterWorkspace({ project, node }: { project: ProjectResponse; node: OutlineNode }) {
  const toast = useToast()
  const projectId = project.project_id
  const chapter = useAsyncData<ChapterResponse>(() => getChapter(projectId, node.node_id), [projectId, node.node_id])
  const versionsData = useAsyncData<ChapterVersion[]>(() => listVersions(projectId, node.node_id), [projectId, node.node_id])
  const [generating, setGenerating] = useState(false)
  const [generatingChildren, setGeneratingChildren] = useState(false)

  const reloadAll = () => Promise.all([chapter.reload(), versionsData.reload()])

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      await generateChapter(projectId, node.node_id)
      toast.success("章节内容已生成并保存为新版本")
      await reloadAll()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败")
    } finally {
      setGenerating(false)
    }
  }

  const handleGenerateChildren = async () => {
    setGeneratingChildren(true)
    try {
      const result = await generateChildChapters(projectId, node.node_id, true, true, 8)
      toast.success(`子章节生成完成：生成 ${result.generated.length}，跳过 ${result.skipped.length}`)
      await reloadAll()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "子章节生成失败")
    } finally {
      setGeneratingChildren(false)
    }
  }

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
            <Button variant="outline" onClick={handleGenerateChildren} loading={generatingChildren} icon={<GitBranch className="h-4 w-4" />}>
              生成子章节
            </Button>
            <Button onClick={handleGenerate} loading={generating} icon={<Wand2 className="h-4 w-4" />}>
              {chapter.data?.markdown?.trim() ? "重新生成本章" : "生成本章"}
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <div className="flex min-w-0 flex-col gap-5">
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

function SourcePanel({ projectId, chapter, loading }: { projectId: string; chapter: ChapterResponse | null; loading: boolean }) {
  const mapping = chapter?.source_mapping
  const toast = useToast()
  const [section, setSection] = useState<SourceSection | null>(null)
  const [loadingSectionId, setLoadingSectionId] = useState<string | null>(null)

  const openSection = async (sectionId: string) => {
    setLoadingSectionId(sectionId)
    try {
      setSection(await getSourceSection(projectId, sectionId))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "读取原文失败")
    } finally {
      setLoadingSectionId(null)
    }
  }

  return (
    <>
      <Card className="p-5">
        <SectionTitle title="来源映射" description="这些原文只用于进入提示词和人工追溯；点击按钮单独查看，不混入正文预览或最终成稿。" />
        {loading ? (
          <LoadingBlock label="加载来源..." />
        ) : !mapping?.matches?.length ? (
          <p className="mt-3 text-xs text-muted-foreground">暂无来源映射。生成本章后会展示匹配章节与证据。</p>
        ) : (
          <ul className="mt-3 grid gap-2 md:grid-cols-2">
            {mapping.matches.map((m) => (
              <li key={`${m.section_id}-${m.usage}`} className="rounded-[var(--radius)] border border-border bg-muted/30 p-3">
                <p className="truncate text-xs font-semibold text-foreground">{m.title_path.join(" / ")}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{m.reason}</p>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <p className="min-w-0 truncate text-[11px] text-muted-foreground">
                    {m.section_id} · {m.usage} · {(m.confidence * 100).toFixed(0)}%
                  </p>
                  <Button size="sm" variant="outline" loading={loadingSectionId === m.section_id} onClick={() => openSection(m.section_id)} icon={<FileText className="h-3.5 w-3.5" />}>
                    查看原文
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {section ? <SourceSectionModal section={section} onClose={() => setSection(null)} /> : null}
    </>
  )
}

function SourceSectionModal({ section, onClose }: { section: SourceSection; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4">
      <div className="flex max-h-[86vh] w-[min(980px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{section.title_path.join(" / ")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {section.section_id} · {section.source_file}
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="关闭原文查看">
            <X className="h-4 w-4" />
          </button>
        </div>
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
  const [mode, setMode] = useState<"preview" | "edit">("preview")
  const [draft, setDraft] = useState(chapter?.markdown ?? "")
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
            预览
          </TabBtn>
          <TabBtn
            active={mode === "edit"}
            onClick={() => {
              setDraft(chapter.markdown)
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
            <Markdown content={chapter.markdown} />
          </div>
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
