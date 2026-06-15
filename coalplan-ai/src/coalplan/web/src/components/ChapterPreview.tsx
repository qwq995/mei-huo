import type { SourceMatch, TemplateNode } from "../api";

type ChapterPreviewProps = {
  node?: TemplateNode | null;
  markdown: string;
  sourceMatches: SourceMatch[];
  busy: boolean;
  onGenerateOne: () => Promise<void>;
  onRefresh: () => Promise<void>;
};

export function ChapterPreview({ node, markdown, sourceMatches, busy, onGenerateOne, onRefresh }: ChapterPreviewProps) {
  return (
    <section className="panel preview-panel">
      <div className="panel-heading">
        <h2>单章结果</h2>
        <span className="status">{node?.title ?? "未选择"}</span>
      </div>
      <div className="actions compact">
        <button disabled={!node || busy} onClick={() => void onGenerateOne()}>
          重跑本章
        </button>
        <button disabled={!node || busy} onClick={() => void onRefresh()}>
          刷新
        </button>
      </div>
      <div className="source-strip">
        <h3>来源片段</h3>
        {sourceMatches.length > 0 ? (
          sourceMatches.map((match) => (
            <article key={match.section_id} className="source-item">
              <strong>{match.title_path.join(" > ")}</strong>
              <p>{match.snippet}</p>
            </article>
          ))
        ) : (
          <p className="empty-text">选择已生成章节后显示召回来源。</p>
        )}
      </div>
      <pre className="markdown-preview chapter">{markdown || "选择模板小章节后，可查看或单独重跑该章生成结果。"}</pre>
    </section>
  );
}
