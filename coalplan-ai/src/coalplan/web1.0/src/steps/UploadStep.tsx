import { useCallback, useRef, useState } from "react"
import { ArrowRight, CheckCircle2, FileText, Trash2, UploadCloud } from "lucide-react"
import { uploadBidMarkdown, type ProjectResponse } from "@/lib/api"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, SectionTitle } from "@/components/ui"
import { cn } from "@/lib/utils"

type UploadedFile = { name: string; size: number; chars: number }

export function UploadStep({ project, onNext }: { project: ProjectResponse; onNext: () => void }) {
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
          await uploadBidMarkdown(project.project_id, file.name, content)
          setFiles((prev) => [...prev, { name: file.name, size: file.size, chars: content.length }])
          ok += 1
        } catch (err) {
          toast.error(`${file.name} 上传失败：${err instanceof Error ? err.message : ""}`)
        }
      }
      setUploading(false)
      if (ok > 0) toast.success(`已上传 ${ok} 个文件`)
    },
    [project.project_id, toast],
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
            <Stat label="资料" value={project.source_document_count + files.length} />
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
      </div>
    </div>
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
