import { useRef, useState } from "react"
import { FileImage, ImagePlus, Paperclip, Plus, Trash2 } from "lucide-react"
import {
  addSupplement,
  deleteAttachment,
  deleteSupplement,
  getWorkspace,
  uploadAttachment,
  type ChapterAttachment,
  type ChapterSupplement,
} from "@/lib/api"
import { useAsyncData } from "@/lib/useAsync"
import { useToast } from "@/components/Toast"
import { Button, Card, EmptyState, LoadingBlock, SectionTitle, TextArea, TextInput } from "@/components/ui"
import { cn, formatDateTime } from "@/lib/utils"

export function AttachmentPanel({ projectId, nodeId }: { projectId: string; nodeId: string }) {
  const toast = useToast()
  const workspace = useAsyncData(() => getWorkspace(projectId, nodeId), [projectId, nodeId])
  const supplements = workspace.data?.supplements ?? []
  const attachments = workspace.data?.attachments ?? []

  return (
    <div className="flex flex-col gap-5">
      <SupplementBox
        projectId={projectId}
        nodeId={nodeId}
        supplements={supplements}
        loading={workspace.loading}
        onChanged={() => workspace.reload()}
      />
      <AttachmentBox
        projectId={projectId}
        nodeId={nodeId}
        attachments={attachments}
        loading={workspace.loading}
        onChanged={() => workspace.reload()}
      />
      {workspace.error ? <p className="rounded-[var(--radius)] bg-[color-mix(in_srgb,var(--color-danger)_10%,transparent)] p-3 text-xs text-[var(--color-danger)]">{workspace.error}</p> : null}
    </div>
  )
}

function SupplementBox({
  projectId,
  nodeId,
  supplements,
  loading,
  onChanged,
}: {
  projectId: string
  nodeId: string
  supplements: ChapterSupplement[]
  loading: boolean
  onChanged: () => void
}) {
  const toast = useToast()
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [mustInclude, setMustInclude] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const save = async () => {
    if (!title.trim() && !content.trim()) {
      toast.error("请填写补充标题或内容")
      return
    }
    setSaving(true)
    try {
      await addSupplement(projectId, nodeId, {
        kind: "text",
        title: title.trim() || "人工补充",
        content: content.trim(),
        must_include: mustInclude,
      })
      setTitle("")
      setContent("")
      setMustInclude(true)
      toast.success("补充材料已保存")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: string) => {
    setDeletingId(id)
    try {
      await deleteSupplement(projectId, nodeId, id)
      toast.success("补充材料已删除")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Card className="p-4">
      <SectionTitle title="人工补充" description="会随本章生成 prompt 一起进入模型，可用于补现场说明、表格或修改要求。" />
      <div className="mt-3 flex flex-col gap-3">
        <TextInput value={title} onChange={(e) => setTitle(e.target.value)} placeholder="补充标题，例如：现场运输条件" className="h-9 text-xs" />
        <TextArea value={content} onChange={(e) => setContent(e.target.value)} rows={4} placeholder="输入正文、Markdown 表格或必须写入的要点" />
        <div className="flex items-center justify-between gap-2">
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={mustInclude} onChange={(e) => setMustInclude(e.target.checked)} className="accent-[var(--color-primary)]" />
            生成时必须写入
          </label>
          <Button size="sm" onClick={save} loading={saving} icon={<Plus className="h-3.5 w-3.5" />}>
            保存补充
          </Button>
        </div>
        {loading ? (
          <LoadingBlock label="加载补充材料..." />
        ) : !supplements.length ? (
          <EmptyState title="暂无补充材料" description="刷新页面后仍会从数据库恢复。" />
        ) : (
          <ul className="flex flex-col gap-2">
            {supplements.map((item) => (
              <li key={item.id} className="rounded-[var(--radius)] border border-border bg-card p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold text-foreground">{item.title}</p>
                    <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{item.content}</p>
                  </div>
                  <Button variant="ghost" size="icon" loading={deletingId === item.id} onClick={() => remove(item.id)} aria-label="删除补充材料">
                    {deletingId === item.id ? null : <Trash2 className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

function AttachmentBox({
  projectId,
  nodeId,
  attachments,
  loading,
  onChanged,
}: {
  projectId: string
  nodeId: string
  attachments: ChapterAttachment[]
  loading: boolean
  onChanged: () => void
}) {
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [description, setDescription] = useState("")
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const upload = async (file: File) => {
    setUploading(true)
    try {
      await uploadAttachment(projectId, nodeId, file, description.trim())
      setDescription("")
      toast.success("附件已上传")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败")
    } finally {
      setUploading(false)
    }
  }

  const remove = async (id: string) => {
    setDeletingId(id)
    try {
      await deleteAttachment(projectId, nodeId, id)
      toast.success("附件已删除")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Card className="p-4">
      <SectionTitle title="附件 / 配图说明" right={<Paperclip className="h-4 w-4 text-muted-foreground" />} />
      <div className="mt-3 flex flex-col gap-3">
        <TextInput value={description} onChange={(e) => setDescription(e.target.value)} placeholder="附件说明，例如：施工平面布置图" className="h-9 text-xs" />
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files?.[0]
            if (file) void upload(file)
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-[var(--radius)] border-2 border-dashed px-4 py-6 text-center transition-colors",
            dragging ? "border-primary bg-primary/[0.05]" : "border-border hover:border-primary/40 hover:bg-muted/40",
            uploading && "pointer-events-none opacity-60",
          )}
        >
          <ImagePlus className="h-6 w-6 text-muted-foreground" />
          <p className="text-xs font-medium text-foreground">{uploading ? "上传中..." : "点击或拖拽上传附件"}</p>
          <p className="text-[11px] text-muted-foreground">图片第一版只作为文件引用和说明进入生成上下文</p>
          <input
            ref={inputRef}
            type="file"
            accept="image/*,.pdf,.doc,.docx,.xls,.xlsx"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void upload(file)
              e.target.value = ""
            }}
          />
        </div>
        {loading ? (
          <LoadingBlock label="加载附件..." />
        ) : !attachments.length ? (
          <EmptyState icon={<FileImage className="h-5 w-5" />} title="暂无附件" />
        ) : (
          <ul className="flex flex-col gap-2">
            {attachments.map((a) => (
              <li key={a.id} className="flex items-center gap-2.5 rounded-[var(--radius)] border border-border bg-card p-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded bg-muted text-muted-foreground">
                  <FileImage className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-foreground">{a.file_name}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {a.description || a.content_type} · {formatDateTime(a.created_at)}
                  </p>
                </div>
                <Button variant="ghost" size="icon" loading={deletingId === a.id} onClick={() => remove(a.id)} aria-label="删除附件">
                  {deletingId === a.id ? null : <Trash2 className="h-3.5 w-3.5" />}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}
