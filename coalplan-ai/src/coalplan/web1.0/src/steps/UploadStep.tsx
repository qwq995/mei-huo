import { useCallback, useRef, useState } from "react"
import { ArrowRight, Check, CheckCircle2, FileText, Library, Trash2, UploadCloud, X } from "lucide-react"
import {
  getReferenceLibrarySummary,
  updateReferenceAtomStatus,
  uploadBidMarkdown,
  uploadReferenceMarkdown,
  type ProjectResponse,
  type ReferenceImportResult,
  type ReferenceLibrarySummary,
} from "@/lib/api"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, SectionTitle, TextInput } from "@/components/ui"
import { cn } from "@/lib/utils"
import { useAsyncData } from "@/lib/useAsync"

type UploadedFile = { name: string; size: number; chars: number }

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

  const handleFiles = useCallback(
    async (fileList: FileList | null) => {
      if (!fileList?.length) return
      setUploading(true)
      let ok = 0
      for (const file of Array.from(fileList)) {
        try {
          const content = await file.text()
          const updatedProject = await uploadBidMarkdown(project.project_id, file.name, content)
          onProjectUpdated(updatedProject)
          setFiles((prev) => [...prev, { name: file.name, size: file.size, chars: content.length }])
          ok += 1
        } catch (err) {
          toast.error(`${file.name} 上传失败：${err instanceof Error ? err.message : ""}`)
        }
      }
      setUploading(false)
      if (ok > 0) {
        toast.success(`已上传 ${ok} 个文件`)
        onExperienceChanged()
      }
    },
    [onExperienceChanged, onProjectUpdated, project.project_id, toast],
  )

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
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
                    <p className="text-xs text-muted-foreground">
                      {(f.size / 1024).toFixed(1)} KB · {f.chars.toLocaleString()} 字符
                    </p>
                  </div>
                  <CheckCircle2 className="h-4.5 w-4.5 text-[var(--color-success)]" />
                  <button onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))} className="rounded p-1 text-muted-foreground hover:text-[var(--color-danger)]" aria-label="从列表移除">
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
        <ReferenceLibraryPanel onChanged={onExperienceChanged} />
        <Card className="p-5">
          <p className="text-sm font-medium text-foreground">下一步：目录工作台</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">上传完成后，生成可编辑目录，再进行目录扩细、字数估算和逐章生成。</p>
          <Button className="mt-4 w-full" onClick={onNext} loading={uploading} icon={<ArrowRight className="h-4 w-4" />}>
            进入目录工作台
          </Button>
        </Card>
      </div>
    </div>
  )
}

function ReferenceLibraryPanel({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const summary = useAsyncData<ReferenceLibrarySummary>(() => getReferenceLibrarySummary(), [])
  const inputRef = useRef<HTMLInputElement>(null)
  const [projectName, setProjectName] = useState("")
  const [projectType, setProjectType] = useState("水电/隧洞/边坡")
  const [uploading, setUploading] = useState(false)
  const [reviewingId, setReviewingId] = useState<string | null>(null)
  const [lastImport, setLastImport] = useState<ReferenceImportResult | null>(null)
  const [showAllCandidates, setShowAllCandidates] = useState(false)

  const importFile = async (file?: File) => {
    if (!file) return
    const effectiveProjectName = projectName.trim() || file.name.replace(/\.(md|markdown|txt)$/i, "")
    if (!projectName.trim()) setProjectName(effectiveProjectName)
    setUploading(true)
    try {
      const result = await uploadReferenceMarkdown({
        file_name: file.name,
        content: await file.text(),
        project_name: effectiveProjectName,
        project_type: projectType.trim() || "未分类",
        max_batches: 3,
      })
      setLastImport(result)
      if (result.processing_status === "success") toast.success(result.user_message)
      else if (result.processing_status === "partial") toast.info(result.user_message)
      else toast.error(result.user_message)
      await summary.reload()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "参考文档处理失败")
    } finally {
      setUploading(false)
    }
  }

  const review = async (atomId: string, status: "published" | "rejected") => {
    setReviewingId(atomId)
    try {
      await updateReferenceAtomStatus(atomId, status)
      toast.success(status === "published" ? "原子已发布，可参与后续匹配" : "已排除该候选原子")
      await summary.reload()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "状态更新失败")
    } finally {
      setReviewingId(null)
    }
  }

  const data = summary.data
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
      <Button className="mt-2 w-full" variant="outline" loading={uploading} onClick={() => inputRef.current?.click()} icon={<UploadCloud className="h-4 w-4" />}>
        上传一份优秀施组并自动切分
      </Button>
      <p className="mt-2 text-[11px] text-muted-foreground">
        {data ? `${data.document_count} 份文档 · ${data.atom_count} 条原子 · ${data.published_count} 条已发布。${data.message}` : "正在读取参考库状态..."}
      </p>
      {lastImport ? (
        <div className={cn("mt-2 border-l-2 px-3 py-1.5 text-[11px] leading-relaxed", lastImport.processing_status === "failed" ? "border-[var(--color-danger)] text-[var(--color-danger)]" : "border-primary/40 text-muted-foreground")}>
          <p>{lastImport.user_message}</p>
          <p>{lastImport.llm_call_count} 次模型调用 · {lastImport.failed_batch_count} 个缩批后仍失败的批次</p>
        </div>
      ) : null}
      {data?.candidate_atoms.length ? (
        <ul className="mt-3 max-h-56 space-y-2 overflow-y-auto">
          {data.candidate_atoms.slice(0, showAllCandidates ? data.candidate_atoms.length : 5).map((atom) => (
            <li key={atom.atom_id} className="border-l-2 border-primary/25 pl-3">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-foreground">{atom.title_path.join(" / ") || atom.process}</p>
                  <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{atom.excerpt}</p>
                  <p className="mt-1 text-[10px] text-muted-foreground">{atom.project_name} · 质量分 {atom.quality_score.toFixed(2)}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button title="排除" aria-label="排除候选原子" size="icon" variant="ghost" loading={reviewingId === atom.atom_id} onClick={() => review(atom.atom_id, "rejected")} icon={<X className="h-4 w-4" />} />
                  <Button title="审核并发布" aria-label="审核并发布原子" size="icon" variant="ghost" loading={reviewingId === atom.atom_id} onClick={() => review(atom.atom_id, "published")} icon={<Check className="h-4 w-4 text-[var(--color-success)]" />} />
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {data && data.candidate_atoms.length > 5 ? (
        <Button
          className="mt-2 w-full"
          size="sm"
          variant="ghost"
          onClick={() => setShowAllCandidates((value) => !value)}
        >
          {showAllCandidates ? "收起候选" : `查看全部 ${data.candidate_count} 条候选`}
        </Button>
      ) : null}
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius)] bg-muted/50 py-3">
      <p className="text-xl font-semibold text-foreground">{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
