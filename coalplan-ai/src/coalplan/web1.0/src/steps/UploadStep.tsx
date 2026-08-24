import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowRight, Check, CheckCircle2, FileText, Library, Loader2, RotateCcw, Search, Trash2, UploadCloud, X } from "lucide-react"
import {
  getReferenceLibrarySummary,
  listReferenceAtoms,
  updateReferenceAtomStatus,
  uploadBidMarkdown,
  type ProjectResponse,
  type ReferenceImportResult,
  type ReferenceLibrarySummary,
  type ReferenceAtomDetail,
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

  const uploadSingle = useCallback(async (file: File, id: string) => {
    try {
      const content = await file.text()
      const updatedProject = await uploadBidMarkdown(project.project_id, file.name, content)
      onProjectUpdated(updatedProject)
      setFiles((prev) => prev.map((item) => item.id === id ? { ...item, chars: content.length, status: "success", error: undefined } : item))
      return true
    } catch (err) {
      const message = err instanceof Error ? err.message : "上传失败"
      setFiles((prev) => prev.map((item) => item.id === id ? { ...item, status: "failed", error: message } : item))
      return false
    }
  }, [onProjectUpdated, project.project_id])

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
      {view === "bid" ? <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <Card className="p-5">
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
            "mt-4 flex cursor-pointer flex-col items-center justify-center gap-3 rounded-[var(--radius)] border-2 border-dashed px-6 py-14 text-center transition-colors",
            dragging ? "border-primary bg-primary/[0.05]" : "border-border hover:border-primary/40 hover:bg-muted/40",
          )}
        >
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
            <UploadCloud className="h-7 w-7" />
          </span>
          <div>
            <p className="text-sm font-medium text-foreground">拖拽文件到此处，或点击选择</p>
            <p className="mt-1 text-xs text-muted-foreground">支持 .md / .markdown / .txt，可一次选择多个</p>
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
            <EmptyState icon={<FileText className="h-6 w-6" />} title="暂未上传文件" description="上传后即可进入目录生成与精修。" />
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
      </Card>

      <div className="flex flex-col gap-4">
        <Card className="p-5">
          <SectionTitle title="当前工程" />
          <dl className="mt-4 grid grid-cols-3 gap-3 text-center">
            <Stat label="资料" value={project.source_document_count} />
            <Stat label="切章" value={project.section_count} />
            <Stat label="运行" value={project.run_count} />
          </dl>
        </Card>
        <Card className="p-5">
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

  useEffect(() => {
    const finished = (event: Event) => {
      const job = (event as CustomEvent).detail
      if (job?.project_id !== projectId || job?.job_type !== "reference_import") return
      if (job.result?.processing_status) setLastImport(job.result as ReferenceImportResult)
      void Promise.all([summary.reload(), atoms.reload()]).then(onChanged)
    }
    window.addEventListener("coalplan:job-finished", finished)
    return () => window.removeEventListener("coalplan:job-finished", finished)
  }, [atoms.reload, onChanged, projectId, summary.reload])

  const review = async (atomId: string, status: "published" | "rejected") => {
    setReviewingId(atomId)
    try {
      await updateReferenceAtomStatus(atomId, status)
      setLastReviewedIds([atomId])
      toast.success(status === "published" ? "原子已发布，可参与后续匹配" : "已排除该候选原子")
      await summary.reload()
      await atoms.reload()
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
      await Promise.all([summary.reload(), atoms.reload()])
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
      await Promise.all([summary.reload(), atoms.reload()])
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "撤销失败")
    }
  }
  return (
    <Card className="p-5">
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
        onChange={(e) => {
          void importFile(e.target.files?.[0])
          e.target.value = ""
        }}
      />
      <Button className="mt-2 w-full" variant="outline" loading={uploading || activeJob?.job_type === "reference_import"} onClick={() => inputRef.current?.click()} icon={<UploadCloud className="h-4 w-4" />}>
        上传一份优秀施组并自动切分
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
    </Card>
  )
}

function AtomDetailModal({ atom, onClose }: { atom: ReferenceAtomDetail; onClose: () => void }) {
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/35 p-4" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="flex max-h-[86vh] w-[min(860px,96vw)] flex-col rounded-[var(--radius)] border border-border bg-card shadow-2xl"><div className="flex items-start justify-between gap-4 border-b border-border p-5"><div className="min-w-0"><p className="text-sm font-semibold text-foreground">{atom.title_path.join(" / ") || atom.process}</p><p className="mt-1 text-xs text-muted-foreground">{atom.project_name} · 原文 {atom.start_line}-{atom.end_line} 行 · 质量分 {atom.quality_score.toFixed(2)}</p></div><Button size="icon" variant="ghost" onClick={onClose} aria-label="关闭原子详情"><X className="h-4 w-4" /></Button></div><div className="overflow-y-auto p-5"><div className="grid gap-2 sm:grid-cols-3">{[["工程对象",atom.engineering_object],["专业",atom.specialty],["工艺",atom.process],["工序阶段",atom.process_stage],["章节类型",atom.chapter_type],["项目类型",atom.project_type]].map(([label,value]) => <div key={label} className="rounded-[var(--radius)] bg-muted/40 p-2"><p className="text-[10px] text-muted-foreground">{label}</p><p className="mt-0.5 text-xs text-foreground">{value || "未标注"}</p></div>)}</div><div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-foreground">{atom.content}</div>{atom.fact_variables.length ? <div className="mt-4 border-l-2 border-[var(--color-warning)] pl-3"><p className="text-xs font-semibold text-foreground">不得直接迁移的项目变量</p>{atom.fact_variables.map((item) => <p key={`${item.name}-${item.value}`} className="mt-1 text-xs text-muted-foreground">{item.name}：{item.value}</p>)}</div> : null}{atom.applicability.length ? <p className="mt-4 text-xs text-muted-foreground">适用条件：{atom.applicability.join("；")}</p> : null}{atom.prohibited_scenarios.length ? <p className="mt-2 text-xs text-[var(--color-warning)]">禁止套用：{atom.prohibited_scenarios.join("；")}</p> : null}</div></div></div>
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius)] bg-muted/50 py-3">
      <p className="text-xl font-semibold text-foreground">{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
