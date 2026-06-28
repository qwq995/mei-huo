import { useMemo } from "react"
import { marked } from "marked"
import { cn } from "@/lib/utils"

marked.setOptions({ gfm: true, breaks: true })

export function Markdown({ content, className }: { content: string; className?: string }) {
  const html = useMemo(() => {
    if (!content?.trim()) return ""
    try {
      return marked.parse(content) as string
    } catch {
      return ""
    }
  }, [content])

  if (!content?.trim()) {
    return <p className="text-sm italic text-muted-foreground">（暂无内容）</p>
  }

  return <div className={cn("prose-doc", className)} dangerouslySetInnerHTML={{ __html: html }} />
}
