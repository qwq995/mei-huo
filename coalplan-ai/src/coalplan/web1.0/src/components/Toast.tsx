import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react"
import { cn } from "@/lib/utils"

type ToastKind = "success" | "error" | "info"
type ToastItem = { id: number; kind: ToastKind; message: string }

type ToastApi = {
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error("useToast must be used within ToastProvider")
  return ctx
}

const icons: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4 text-[var(--color-success)]" />,
  error: <AlertCircle className="h-4 w-4 text-[var(--color-danger)]" />,
  info: <Info className="h-4 w-4 text-primary" />,
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = Date.now() + Math.random()
      setItems((prev) => [...prev, { id, kind, message }])
      window.setTimeout(() => remove(id), 4200)
    },
    [remove],
  )

  const api = useMemo<ToastApi>(
    () => ({
      success: (m) => push("success", m),
      error: (m) => push("error", m),
      info: (m) => push("info", m),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(92vw,380px)] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            className={cn("animate-fade-in pointer-events-auto flex items-start gap-2.5 rounded-[var(--radius)] border border-border bg-card px-3.5 py-3 shadow-lg shadow-black/5")}
          >
            <span className="mt-0.5 shrink-0">{icons[t.kind]}</span>
            <p className="flex-1 text-sm leading-relaxed text-foreground">{t.message}</p>
            <button onClick={() => remove(t.id)} className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted" aria-label="关闭通知">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
