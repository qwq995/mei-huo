import type { RunResponse } from "../api";

type GenerationProgressProps = {
  run?: RunResponse | null;
};

export function GenerationProgress({ run }: GenerationProgressProps) {
  return (
    <section className="panel progress-panel">
      <div className="panel-heading">
        <h2>生成状态</h2>
        <span className="status">{run?.status ?? "待启动"}</span>
      </div>
      <div className="stats">
        <Metric label="总章节" value={run?.task_count ?? 0} />
        <Metric label="已通过" value={run?.passed_count ?? 0} />
        <Metric label="失败" value={run?.failed_count ?? 0} />
      </div>
      <div className="log-list">
        {(run?.logs ?? ["等待上传 Markdown 并启动生成流程"]).map((log, index) => (
          <p key={`${index}-${log}`}>{log}</p>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
