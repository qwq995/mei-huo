type FinalDocumentPreviewProps = {
  markdown: string;
};

export function FinalDocumentPreview({ markdown }: FinalDocumentPreviewProps) {
  return (
    <section className="panel final-panel">
      <div className="panel-heading">
        <h2>合并结果</h2>
        <span className="status">{markdown ? "已生成" : "待合并"}</span>
      </div>
      <pre className="markdown-preview final">{markdown || "所有通过的小章节会按模板目录顺序合并为 final.md。"}</pre>
    </section>
  );
}
