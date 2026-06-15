import type { ProjectResponse } from "../api";

type UploadPanelProps = {
  project?: ProjectResponse | null;
  busy: boolean;
  onCreate: (name: string) => Promise<void>;
  onUpload: (fileName: string, content: string) => Promise<void>;
  onRun: () => Promise<void>;
};

export function UploadPanel({ project, busy, onCreate, onUpload, onRun }: UploadPanelProps) {
  async function handleFile(file?: File | null) {
    if (!file) return;
    const content = await file.text();
    await onUpload(file.name, content);
  }

  return (
    <section className="panel upload-panel">
      <div className="panel-heading">
        <h2>项目输入</h2>
        <span className="status">{project ? `${project.section_count} 节来源` : "未创建"}</span>
      </div>

      <label className="field">
        <span>项目名称</span>
        <input
          type="text"
          defaultValue="宁夏煤火治理施组演示"
          disabled={busy || Boolean(project)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !project) {
              void onCreate(event.currentTarget.value.trim() || "火区治理施组演示");
            }
          }}
        />
      </label>

      <div className="actions">
        <button disabled={busy || Boolean(project)} onClick={() => onCreate("宁夏煤火治理施组演示")}>
          创建项目
        </button>
        <label className={`file-button ${!project || busy ? "disabled" : ""}`}>
          上传投标 Markdown
          <input
            type="file"
            accept=".md,.markdown,text/markdown,text/plain"
            disabled={!project || busy}
            onChange={(event) => void handleFile(event.currentTarget.files?.[0])}
          />
        </label>
        <button disabled={!project || busy || project.section_count === 0} onClick={() => void onRun()}>
          生成并合并
        </button>
      </div>
    </section>
  );
}
