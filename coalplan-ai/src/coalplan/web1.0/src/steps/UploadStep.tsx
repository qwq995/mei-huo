import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowRight, Check, CheckCircle2, FileText, Library, Loader2, RotateCcw, Search, Trash2, UploadCloud, X } from "lucide-react"
import {
  getReferenceLibrarySummary,
  getReferenceManagement,
  listProjectSourceDocuments,
  listReferenceAtoms,
  updateReferenceAtomStatus,
  updateReferenceAtom,
  deleteReferenceDocument,
  updateReferenceDocument,
  uploadBidMarkdown,
  type ProjectResponse,
  type ReferenceImportResult,
  type ReferenceLibrarySummary,
  type ReferenceAtomDetail,
  type ReferenceManagementResponse,
  type ProjectSourceDocument,
} from "@/lib/api"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, SectionTitle, TextInput } from "@/components/ui"
import { cn } from "@/lib/utils"
import { useAsyncData } from "@/lib/useAsync"
import { useJobs } from "@/components/Jobs"

type UploadedFile = { id: string; name: string; size: number; chars: number; status: "uploading" | "success" | "failed"; error?: string; file: File }

export function UploadStep({
  project,
  onNext,
  onExperienceChanged,
  onProjectUpdated,
}: {
  project: ProjectResponse;
  onNext: () => void;
  onExperienceChanged: () => void;
  onProjectUpdated: (project: ProjectResponse) => void;
}) {
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [view, setView] = useState<"bid" | "reference">("bid")
  const storedDocuments = useAsyncData<ProjectSourceDocument[]>(() => listProjectSourceDocuments(project.project_id), [project.project_id])

  const uploadSingle = useCallback(async (file: File, id: string) => {
    try {
      const content = await file.text()
      const updatedProject = await uploadBidMarkdown(project.project_id, file.name, content)
      onProjectUpdated(updatedProject)
      await storedDocuments.reload()
      setFiles((prev) => prev.map((item) => item.id === id ? { ...item, chars: content.length, status: "success", error: undefined } : item))
      return true
    } catch (err) {
      const message = err instanceof Error ? err.message : "上传失败"
      setFiles((prev) => prev.map((item) => item.id === id ? { ...item, status: "failed", error: message } : item))
      return false
    }
  }, [onProjectUpdated, project.project_id, storedDocuments.reload])

  const handleFiles = useCallback(
    async (fileList: FileList | null) => {
      if (!fileList?.length) return
      setUploading(true)
      let ok = 0
      for (const file of Array.from(fileList)) {
        const id = `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`
        setFiles((prev) => [...prev, { id, name: file.name, size: file.size, chars: 0, status: "uploading", file }])
        if (await uploadSingle(file, id)) ok += 1
      }
      setUploading(false)
      if (ok > 0) {
        toast.success(`已上传 ${ok} 个文件`)
        onExperienceChanged()
      }
    },
    [onExperienceChanged, toast, uploadSingle],
  )

  const retryFile = async (item: UploadedFile) => {
    setFiles((prev) => prev.map((file) => file.id === item.id ? { ...file, status: "uploading", error: undefined } : file))
    if (await uploadSingle(item.file, item.id)) {
      toast.success(`${item.name} 已重新上传`)
      onExperienceChanged()
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="inline-flex w-fit rounded-[var(--radius)] border border-border bg-card p-1">
        <button onClick={() => setView("bid")} className={cn("rounded-[calc(var(--radius)-2px)] px-4 py-2 text-sm font-medium", view === "bid" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>项目投标资料</button>
        <button onClick={() => setView("reference")} className={cn("rounded-[calc(var(--radius)-2px)] px-4 py-2 text-sm font-medium", view === "reference" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>优秀施组参考库</button>
      </div>
      {view === "bid" ? <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:gap-6">
      <Card className="min-w-0 p-4 sm:p-5">
        <SectionTitle title="上传投标 / 技术资料" description="第一阶段建议上传标准化后的 Markdown。系统会切章、生成目录和后续来源映射。" />
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            void handleFiles(e.dataTransfer.files)
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "mt-4 flex cursor-pointer flex-col items-center justify-center gap-2.5 rounded-[var(--radius)] border-2 border-dashed px-4 py-9 text-center transition-colors sm:gap-3 sm:px-6 sm:py-12",
            dragging ? "border-primary bg-primary/[0.05]" : "border-border hover:border-primary/40 hover:bg-muted/40",
          )}
        >
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary sm:h-14 sm:w-14">
            <UploadCloud className="h-5 w-5 sm:h-7 sm:w-7" />
          </span>
          <div>
            <p className="text-sm font-medium text-foreground">拖拽文件到此处，或点击选择</p>
            <p className="mt-1 max-w-[260px] text-xs leading-relaxed text-muted-foreground">支持 .md / .markdown / .txt，可一次选择多个</p>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".md,.markdown,.txt,text/markdown,text/plain"
            multiple
            hidden
            onChange={(e) => {
              void handleFiles(e.target.files)
              e.target.value = ""
            }}
          />
        </div>

        <div className="mt-5">
          <p className="mb-2 text-xs font-medium text-muted-foreground">本次会话上传记录</p>
          {!files.length ? (
            <EmptyState className="py-7 sm:py-10" icon={<FileText className="h-6 w-6" />} title="暂未上传文件" description="上传后即可进入目录生成与精修。" />
          ) : (
            <ul className="flex flex-col gap-2">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`} className="flex items-center gap-3 rounded-[var(--radius)] border border-border bg-card p-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-[var(--radius)] bg-muted text-muted-foreground">
                    <FileText className="h-4.5 w-4.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{f.name}</p>
                    <p className="text-xs text-muted-foreground">{(f.size / 1024).toFixed(1)} KB · {f.status === "uploading" ? "正在读取并切章" : f.status === "success" ? `${f.chars.toLocaleString()} 字符，已完成切章` : f.error}</p>
                  </div>
                  {f.status === "uploading" ? <Loader2 className="h-4.5 w-4.5 animate-spin text-primary" /> : f.status === "success" ? <CheckCircle2 className="h-4.5 w-4.5 text-[var(--color-success)]" /> : <button onClick={() => void retryFile(f)} className="rounded p-1 text-[var(--color-warning)] hover:bg-muted" aria-label="重试上传"><RotateCcw className="h-4 w-4" /></button>}
                  <button title="仅清除本次显示记录，不删除服务器资料" onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))} className="rounded p-1 text-muted-foreground hover:text-[var(--color-danger)]" aria-label="清除本次记录">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <StoredDocumentsPanel documents={storedDocuments.data ?? []} loading={storedDocuments.loading} error={storedDocuments.error ?? undefined} onRefresh={() => void storedDocuments.reload()} />
      </Card>

      <div className="min-w-0 flex flex-col gap-4">
        <Card className="p-5">
          <SectionTitle title="当前工程" />
          <dl className="mt-4 grid grid-cols-3 gap-3 text-center">
            <Stat label="资料" value={project.source_document_count} />
            <Stat label="切章" value={project.section_count} />
            <Stat label="运行" value={project.run_count} />
          </dl>
        </Card>
        <Card className="p-4 sm:p-5">
          <p className="text-sm font-medium text-foreground">下一步：目录工作台</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">上传完成后，生成可编辑目录，再进行目录扩细、字数估算和逐章生成。</p>
          <Button className="mt-4 w-full" onClick={onNext} loading={uploading} icon={<ArrowRight className="h-4 w-4" />}>
            进入目录工作台
          </Button>
        </Card>
      </div></div> : <div className="grid gap-6 lg:grid-cols-[1fr_320px]"><ReferenceLibraryPanel projectId={project.project_id} onChanged={onExperienceChanged} /><Card className="h-fit p-5"><SectionTitle title="两类资料互不混用" /><div className="mt-4 space-y-3 text-xs leading-relaxed text-muted-foreground"><p><strong className="text-foreground">投标资料</strong>决定本项目可以写入的名称、参数、工程量和事实。</p><p><strong className="text-foreground">优秀施组原子</strong>只补充工序展开和控制方法，发布前不会参与生成。</p></div></Card></div>}
    </div>
  )
}

function ReferenceLibraryPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const toast = useToast()
  const { startJob, activeJob } = useJobs()
  const summary = useAsyncData<ReferenceLibrarySummary>(() => getReferenceLibrarySummary(), [])
  const management = useAsyncData<ReferenceManagementResponse>(() => getReferenceManagement(), [])
  const atoms = useAsyncData<ReferenceAtomDetail[]>(() => listReferenceAtoms("ai_candidate"), [])
  const inputRef = useRef<HTMLInputElement>(null)
  const [projectName, setProjectName] = useState("")
  const [projectType, setProjectType] = useState("水电/隧洞/边坡")
  const [uploading, setUploading] = useState(false)
  const [reviewingId, setReviewingId] = useState<string | null>(null)
  const [lastImport, setLastImport] = useState<ReferenceImportResult | null>(null)
  const [showAllCandidates, setShowAllCandidates] = useState(false)
  const [query, setQuery] = useState("")
  const [detail, setDetail] = useState<ReferenceAtomDetail | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [lastReviewedIds, setLastReviewedIds] = useState<string[]>([])

  const importFile = async (file?: File) => {
    if (!file) return
    const effectiveProjectName = projectName.trim() || file.name.replace(/\.(md|markdown|txt)$/i, "")
    if (!projectName.trim()) setProjectName(effectiveProjectName)
    setUploading(true)
    try {
      await startJob("reference_import", {
        file_name: file.name,
        content: await file.text(),
        project_name: effectiveProjectName,
        project_type: projectType.trim() || "未分类",
        max_batches: 3,
      })
      toast.success("优秀施组切分已开始，可离开本页并在任务中心查看进度")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "参考文档处理失败")
    } finally {
      setUploading(false)
    }
  }

  const importFiles = async (files: File[]) => {
    if (!files.length) return
    setUploading(true)
    try {
      const defaultName = projectName.trim()
      const payload = await Promise.all(files.map(async (file) => ({ file_name: file.name, content: await file.text(), project_name: defaultName || file.name.replace(/\.(md|markdown|txt)$/i, ""), project_type: projectType.trim() || "未分类", max_batches: 3 })))
      await startJob("reference_import_batch", { files: payload })
      toast.success(`已提交 ${files.length} 份文档，完成一份就会立即进入管理台`)
    } catch (err) { toast.error(err instanceof Error ? err.message : "批量导入失败") }
    finally { setUploading(false) }
  }

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id !== projectId || !["reference_import", "reference_import_batch"].includes(job?.job_type)) return
      if (job.result?.processing_status) setLastImport(job.result as ReferenceImportResult)
      void Promise.all([summary.reload(), atoms.reload(), management.reload()]).then(onChanged)
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [atoms.reload, management.reload, onChanged, projectId, summary.reload])

  const review = async (atomId: string, status: "published" | "rejected") => {
    setReviewingId(atomId)
    try {
      await updateReferenceAtomStatus(atomId, status)
      setLastReviewedIds([atomId])
      toast.success(status === "published" ? "原子已发布，可参与后续匹配" : "已排除该候选原子")
      await Promise.all([summary.reload(), atoms.reload(), management.reload()])
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "状态更新失败")
    } finally {
      setReviewingId(null)
    }
  }

  const data = summary.data
  const candidates = (atoms.data ?? []).filter((atom) => !query.trim() || [atom.project_name, atom.project_type, atom.process, atom.specialty, atom.title_path.join(" ")].join(" ").toLowerCase().includes(query.trim().toLowerCase()))
  const reviewSelected = async (status: "published" | "rejected") => {
    try {
      const ids = [...selectedIds]
      for (const atomId of ids) await updateReferenceAtomStatus(atomId, status)
      setLastReviewedIds(ids)
      toast.success(status === "published" ? `已发布 ${ids.length} 条原子` : `已排除 ${ids.length} 条原子`)
      setSelectedIds([])
      await Promise.all([summary.reload(), atoms.reload(), management.reload()])
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "批量审核失败")
    }
  }
  const undoReview = async () => {
    try {
      for (const atomId of lastReviewedIds) await updateReferenceAtomStatus(atomId, "ai_candidate")
      toast.success(`已恢复 ${lastReviewedIds.length} 条候选原子`)
      setLastReviewedIds([])
      await Promise.all([summary.reload(), atoms.reload(), management.reload()])
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "撤销失败")
    }
  }
  return (
        <Card className="p-4 sm:p-5">
      <SectionTitle
        title="优秀施组原子库"
        description="与当前投标资料独立存储。AI 先切分，您抽查发布后才参与生成。"
        right={<Library className="h-4 w-4 text-primary" />}
      />
      <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        {(data?.workflow ?? ["上传", "AI 切分", "抽查", "发布"]).map((item, index) => (
          <span key={item} className="flex items-center gap-2">
            {index ? <span>→</span> : null}<span>{item}</span>
          </span>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <TextInput value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="参考项目名称" />
        <TextInput value={projectType} onChange={(e) => setProjectType(e.target.value)} placeholder="项目类型" />
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".md,.markdown,.txt"
        hidden
        multiple
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length > 1) void importFiles(files)
          else void importFile(files[0])
          e.target.value = ""
        }}
      />
      <Button className="mt-2 w-full" variant="outline" loading={uploading || ["reference_import", "reference_import_batch"].includes(activeJob?.job_type ?? "")} onClick={() => inputRef.current?.click()} icon={<UploadCloud className="h-4 w-4" />}>
        批量上传并自动切分优秀施组
      </Button>
      <p className="mt-2 text-[11px] text-muted-foreground">
        {data ? `${data.document_count} 份文档 · ${data.atom_count} 条原子 · ${data.published_count} 条已发布。${data.message}` : "正在读取参考库状态..."}
      </p>
      {lastReviewedIds.length ? <Button className="mt-2" size="sm" variant="ghost" onClick={() => void undoReview()} icon={<RotateCcw className="h-3.5 w-3.5" />}>撤销最近审核（{lastReviewedIds.length} 条）</Button> : null}
      {lastImport ? (
        <div className={cn("mt-2 border-l-2 px-3 py-1.5 text-[11px] leading-relaxed", lastImport.processing_status === "failed" ? "border-[var(--color-danger)] text-[var(--color-danger)]" : "border-primary/40 text-muted-foreground")}>
          <p>{lastImport.user_message}</p>
          <p>{lastImport.llm_call_count} 次模型调用 · {lastImport.failed_batch_count} 个缩批后仍失败的批次</p>
        </div>
      ) : null}
      {atoms.data?.length ? <div className="mt-3 flex items-center gap-2"><div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><TextInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选项目、工艺或专业" className="pl-9" /></div>{selectedIds.length ? <><Button size="sm" variant="outline" onClick={() => void reviewSelected("rejected")}>排除 {selectedIds.length}</Button><Button size="sm" onClick={() => void reviewSelected("published")}>发布 {selectedIds.length}</Button></> : null}</div> : null}
      {candidates.length ? (
        <ul className="mt-3 max-h-56 space-y-2 overflow-y-auto">
          {candidates.slice(0, showAllCandidates ? candidates.length : 5).map((atom) => (
            <li key={atom.id} className="border-l-2 border-primary/25 pl-3">
              <div className="flex items-start gap-2">
                <input type="checkbox" checked={selectedIds.includes(atom.id)} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, atom.id] : current.filter((id) => id !== atom.id))} className="mt-1 accent-[var(--color-primary)]" aria-label="选择候选原子" />
                <div className="min-w-0 flex-1">
                  <button onClick={() => setDetail(atom)} className="block w-full text-left"><p className="truncate text-xs font-medium text-foreground hover:text-primary">{atom.title_path.join(" / ") || atom.process}</p><p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{atom.content}</p></button>
                  <p className="mt-1 text-[10px] text-muted-foreground">{atom.project_name} · {atom.process || atom.specialty || "未标注工艺"} · 质量分 {atom.quality_score.toFixed(2)}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button title="排除" aria-label="排除候选原子" size="icon" variant="ghost" loading={reviewingId === atom.id} onClick={() => review(atom.id, "rejected")} icon={<X className="h-4 w-4" />} />
                  <Button title="审核并发布" aria-label="审核并发布原子" size="icon" variant="ghost" loading={reviewingId === atom.id} onClick={() => review(atom.id, "published")} icon={<Check className="h-4 w-4 text-[var(--color-success)]" />} />
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {candidates.length > 5 ? (
        <Button
          className="mt-2 w-full"
          size="sm"
          variant="ghost"
          onClick={() => setShowAllCandidates((value) => !value)}
        >
          {showAllCandidates ? "收起候选" : `查看全部 ${candidates.length} 条候选`}
        </Button>
      ) : null}
      {detail ? <AtomDetailModal atom={detail} onClose={() => setDetail(null)} /> : null}
      <ReferenceManagementConsole data={management.data ?? undefined} loading={management.loading} error={management.error ?? undefined} onRefresh={() => void management.reload()} onOpenAtom={setDetail} onDeleteDocument={async (id) => { await deleteReferenceDocument(id); await Promise.all([summary.reload(), atoms.reload(), management.reload()]); onChanged(); toast.success("参考文档已移除，原子随文档一并清理") }} />
    </Card>
  )
}

function StoredDocumentsPanel({ documents, loading, error, onRefresh }: { documents: ProjectSourceDocument[]; loading: boolean; error?: string; onRefresh: () => void }) {
  return (
    <div className="mt-5 border-t border-border pt-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-foreground">已上传资料</p>
          <p className="mt-1 text-[11px] text-muted-foreground">这里显示数据库中保存的资料，刷新页面后仍可查看。</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onRefresh} loading={loading} icon={<RotateCcw className="h-3.5 w-3.5" />}>刷新</Button>
      </div>
      {error ? <div className="mt-3 flex items-center justify-between gap-3 rounded-[var(--radius)] border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 p-3 text-xs text-[var(--color-danger)]"><span>{error}</span><Button size="sm" variant="outline" onClick={onRefresh}>重试</Button></div> : loading && !documents.length ? <div className="mt-3 text-xs text-muted-foreground">正在读取已上传资料...</div> : !documents.length ? <div className="mt-3 rounded-[var(--radius)] border border-dashed border-border p-4 text-center text-xs text-muted-foreground">当前项目还没有持久化资料</div> : (
        <ul className="mt-3 space-y-2">
          {documents.map((document) => <li key={document.id} className="flex items-center gap-3 rounded-[var(--radius)] border border-border bg-muted/20 p-3"><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius)] bg-primary/10 text-primary"><FileText className="h-4 w-4" /></span><div className="min-w-0 flex-1"><p className="truncate text-xs font-medium text-foreground">{document.file_name}</p><p className="mt-1 text-[11px] text-muted-foreground">{document.section_count} 个切章 · {document.character_count.toLocaleString()} 字符 · {document.status === "parsed" ? "已完成解析" : document.status}</p></div><CheckCircle2 className="h-4 w-4 shrink-0 text-[var(--color-success)]" /></li>)}
        </ul>
      )}
    </div>
  )
}

function ReferenceManagementConsole({ data, loading, error, onRefresh, onOpenAtom, onDeleteDocument }: { data?: ReferenceManagementResponse; loading: boolean; error?: string; onRefresh: () => void; onOpenAtom: (atom: ReferenceAtomDetail) => void; onDeleteDocument: (id: string) => Promise<void> }) {
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("all")
  const [documentName, setDocumentName] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [savingDocument, setSavingDocument] = useState(false)
  const toast = useToast()
  useEffect(() => {
    if (!documentId && data?.documents[0]) setDocumentId(data.documents[0].id)
    if (documentId && data && !data.documents.some((item) => item.id === documentId)) setDocumentId(data.documents[0]?.id ?? null)
  }, [data, documentId])
  const selectedAtoms = (data?.atoms ?? []).filter((atom) => (!documentId || atom.document_id === documentId) && (status === "all" || atom.status === status) && (!query.trim() || [atom.content, atom.process, atom.specialty, atom.title_path.join(" ")].join(" ").toLowerCase().includes(query.trim().toLowerCase())))
  const selectedDocument = data?.documents.find((item) => item.id === documentId)
  useEffect(() => { setDocumentName(selectedDocument?.project_name ?? ""); setDocumentType(selectedDocument?.project_type ?? "") }, [selectedDocument?.id])
  const saveDocument = async () => { if (!selectedDocument) return; setSavingDocument(true); try { await updateReferenceDocument(selectedDocument.id, { project_name: documentName.trim(), project_type: documentType.trim() }); toast.success("文档信息已保存"); onRefresh() } catch (err) { toast.error(err instanceof Error ? err.message : "保存文档信息失败") } finally { setSavingDocument(false) } }
  return (
    <div className="mt-5 border-t border-border pt-5">
      <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-foreground">切分管理台</p><p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">先选择来源文档，再检查该文档切分出的原子要素。状态、数量和原文详情均来自数据库。</p></div><Button size="icon" variant="ghost" onClick={onRefresh} loading={loading} aria-label="刷新参考库管理台"><RotateCcw className="h-4 w-4" /></Button></div>
      {error ? <div className="mt-3 flex items-center justify-between gap-3 rounded-[var(--radius)] border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 p-3 text-xs text-[var(--color-danger)]"><span>{error}</span><Button size="sm" variant="outline" onClick={onRefresh}>重试</Button></div> : loading && !data ? <div className="mt-3 text-xs text-muted-foreground">正在读取文档和原子...</div> : !data?.documents.length ? <div className="mt-3 rounded-[var(--radius)] border border-dashed border-border p-4 text-center text-xs text-muted-foreground">还没有完成切分的参考文档</div> : (
        <>
          <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <div className="max-h-64 space-y-2 overflow-y-auto pr-1">{data.documents.map((document) => <div key={document.id} className={cn("rounded-[var(--radius)] border p-3 transition-colors", document.id === documentId ? "border-primary/40 bg-primary/[0.06]" : "border-border hover:bg-muted/40")}><button onClick={() => setDocumentId(document.id)} className="w-full text-left"><p className="truncate text-xs font-semibold text-foreground">{document.file_name}</p><p className="mt-1 truncate text-[11px] text-muted-foreground">{document.project_name} · {document.project_type}</p><div className="mt-2 flex flex-wrap gap-1.5 text-[10px]"><span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">共 {document.atom_counts.total}</span><span className="rounded-full bg-[var(--color-success)]/10 px-2 py-0.5 text-[var(--color-success)]">已发布 {document.atom_counts.published}</span><span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">候选 {document.atom_counts.candidate}</span></div></button><button className="mt-2 text-[11px] text-[var(--color-danger)] hover:underline" onClick={() => { if (window.confirm(`移除“${document.file_name}”？该文档的原子也会被清理。`)) void onDeleteDocument(document.id) }}>移除文档</button></div>)}</div>
            <div className="min-w-0 rounded-[var(--radius)] border border-border p-3"><div className="flex items-center justify-between gap-2"><p className="truncate text-xs font-semibold text-foreground">{selectedDocument?.file_name ?? "全部原子"}</p><span className="shrink-0 text-[10px] text-muted-foreground">{selectedAtoms.length} 条显示</span></div>{selectedDocument ? <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><TextInput value={documentName} onChange={(event) => setDocumentName(event.target.value)} placeholder="参考项目名称" /><TextInput value={documentType} onChange={(event) => setDocumentType(event.target.value)} placeholder="项目类型" /><Button size="sm" variant="outline" loading={savingDocument} onClick={() => void saveDocument()}>保存</Button></div> : null}<div className="mt-2 grid gap-2 sm:grid-cols-[1fr_110px]"><TextInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选工艺、专业或正文" /><select value={status} onChange={(event) => setStatus(event.target.value)} className="h-9 rounded-[var(--radius)] border border-border bg-background px-2 text-xs text-foreground"><option value="all">全部状态</option><option value="published">已发布</option><option value="ai_candidate">候选</option><option value="rejected">已排除</option></select></div>{selectedAtoms.length ? <ul className="mt-3 max-h-52 space-y-2 overflow-y-auto">{selectedAtoms.map((atom) => <li key={atom.id} className="flex items-start gap-2 border-b border-border/70 pb-2 last:border-0"><div className="min-w-0 flex-1"><button className="block w-full text-left" onClick={() => onOpenAtom(atom)}><p className="truncate text-xs font-medium text-foreground hover:text-primary">{atom.title_path.join(" / ") || atom.process || "未命名原子"}</p><p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{atom.content}</p></button><p className="mt-1 text-[10px] text-muted-foreground">{atom.process || atom.specialty || "未标注工艺"} · {atom.status}</p></div><button className="shrink-0 text-[11px] font-medium text-primary hover:underline" onClick={() => onOpenAtom(atom)}>详情</button></li>)}</ul> : <p className="mt-4 text-center text-xs text-muted-foreground">当前筛选条件下没有原子</p>}</div>
          </div>
        </>
      )}
    </div>
  )
}

function AtomDetailModal({ atom, onClose }: { atom: ReferenceAtomDetail; onClose: () => void }) {
  const [content, setContent] = useState(atom.content)
  const [process, setProcess] = useState(atom.process)
  const [saving, setSaving] = useState(false)
  const toast = useToast()
  const save = async () => { setSaving(true); try { await updateReferenceAtom(atom.id, { content, process, applicability: atom.applicability }); toast.success("原子已保存，新版本已记录"); onClose() } catch (err) { toast.error(err instanceof Error ? err.message : "保存原子失败") } finally { setSaving(false) } }
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/35 p-4" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="flex max-h-[86vh] w-[min(860px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl"><div className="flex items-start justify-between gap-4 border-b border-border p-5"><div className="min-w-0"><p className="text-sm font-semibold text-foreground">{atom.title_path.join(" / ") || atom.process}</p><p className="mt-1 text-xs text-muted-foreground">{atom.project_name} · 原文 {atom.start_line}-{atom.end_line} 行 · v{atom.version}</p></div><Button size="icon" variant="ghost" onClick={onClose} aria-label="关闭原子详情"><X className="h-4 w-4" /></Button></div><div className="overflow-y-auto p-5"><div className="grid gap-2 sm:grid-cols-3">{[["工程对象",atom.engineering_object],["专业",atom.specialty],["工艺",process],["工序阶段",atom.process_stage],["章节类型",atom.chapter_type]].map(([label,value]) => <div key={label} className="rounded-[var(--radius)] bg-muted/40 p-2"><p className="text-[10px] text-muted-foreground">{label}</p><p className="mt-0.5 text-xs text-foreground">{value || "未标注"}</p></div>)}</div><label className="mt-4 block text-xs font-medium text-muted-foreground">原子正文<textarea value={content} onChange={(event) => setContent(event.target.value)} className="mt-1 min-h-40 w-full rounded-[var(--radius)] border border-border bg-background p-3 text-sm leading-6 text-foreground" /></label><label className="mt-3 block text-xs font-medium text-muted-foreground">工艺标签<input value={process} onChange={(event) => setProcess(event.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius)] border border-border bg-background px-3 text-sm text-foreground" /></label><div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>取消</Button><Button loading={saving} onClick={() => void save()}>保存原子</Button></div></div></div></div>
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius)] bg-muted/50 py-3">
      <p className="text-xl font-semibold text-foreground">{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
