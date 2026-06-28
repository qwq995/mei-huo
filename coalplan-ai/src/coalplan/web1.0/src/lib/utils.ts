export function cn(...inputs: Array<string | false | null | undefined>): string {
  return inputs.filter(Boolean).join(" ")
}

export function downloadTextFile(filename: string, content: string, mime = "text/markdown;charset=utf-8") {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "-"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  draft: "草稿",
  generated: "已生成",
  generating: "生成中",
  ready: "就绪",
  approved: "已确认",
  selected: "已选用",
  failed: "失败",
  error: "异常",
  completed: "已完成",
  done: "已完成",
  running: "运行中",
  empty: "空",
  missing: "缺失",
  ok: "正常",
  passed: "通过",
  warning: "建议调整",
  blocked: "需处理",
}

export function statusLabel(status?: string | null): string {
  if (!status) return "-"
  return STATUS_LABELS[status.toLowerCase()] ?? status
}

export type StatusTone = "neutral" | "success" | "warning" | "danger" | "info"

export function statusTone(status?: string | null): StatusTone {
  const s = (status ?? "").toLowerCase()
  if (["generated", "ready", "approved", "selected", "completed", "done", "ok", "success", "passed"].includes(s)) {
    return "success"
  }
  if (["generating", "running", "draft", "pending"].includes(s)) return "info"
  if (["missing", "empty", "warning"].includes(s)) return "warning"
  if (["failed", "error", "danger", "blocked"].includes(s)) return "danger"
  return "neutral"
}

export function safeFileName(name: string, fallback = "施工组织设计"): string {
  return (name || fallback).replace(/[\\/:*?"<>|]/g, "_")
}

export function truncateText(value: string | undefined | null, max = 160): string {
  if (!value) return ""
  return value.length > max ? `${value.slice(0, max)}...` : value
}
