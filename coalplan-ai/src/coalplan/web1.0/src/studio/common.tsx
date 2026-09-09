import { useEffect, useRef, useState, type ReactNode } from "react";
import { X, RefreshCw, Search } from "lucide-react";
import MarkdownIt from "markdown-it";
import { API_BASE } from "@/lib/api";

export async function api<T>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(
    API_BASE + path,
    body === undefined
      ? undefined
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `请求失败 (${response.status})`,
    );
  }
  return response.json();
}
export function useResource<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    setData(null);
    load()
      .then((value) => {
        if (alive) setData(value);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [...deps, revision]);
  return { data, error, loading, reload: () => setRevision((x) => x + 1) };
}
export function Status({
  loading,
  error,
  retry,
}: {
  loading: boolean;
  error: string;
  retry: () => void;
}) {
  if (error)
    return (
      <div className="s-alert" role="alert">
        <span>{error}</span>
        <button onClick={retry}>
          <RefreshCw size={15} />
          重试
        </button>
      </div>
    );
  return loading ? (
    <p role="status" className="s-loading">
      正在读取…
    </p>
  ) : null;
}
export function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement;
    ref.current?.showModal();
    return () => {
      before?.focus?.();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`s-modal ${wide ? "wide" : ""}`}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      aria-label={title}
    >
      <header>
        <h2>{title}</h2>
        <button className="s-icon" aria-label="关闭窗口" onClick={close}>
          <X size={19} />
        </button>
      </header>
      <div className="s-modal-body">{children}</div>
    </dialog>
  );
}
export const markdown = new MarkdownIt({
  html: false,
  linkify: false,
  breaks: true,
});
export function Document({ text }: { text: string }) {
  return (
    <div
      className="s-document"
      dangerouslySetInnerHTML={{ __html: markdown.render(text || "暂无正文") }}
    />
  );
}
export function Filter({
  value,
  change,
  placeholder = "搜索",
}: {
  value: string;
  change: (s: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="s-search">
      <Search size={16} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => change(e.target.value)}
      />
    </label>
  );
}
export const statusName = (s: string) =>
  ({
    published: "已发布",
    pending_publish: "待发布",
    ai_candidate: "AI候选",
    reviewed: "已审核",
    rejected: "已排除",
    completed: "已完成",
    running: "执行中",
    queued: "排队中",
    paused: "已暂停",
    failed: "失败",
    interrupted: "已中断",
    partial: "部分完成",
  })[s] || s;
export function download(text: string, name: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/markdown;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
