import type { TemplateNode } from "../api";

type TemplateTreeProps = {
  nodes: TemplateNode[];
  selectedId?: string | null;
  onSelect: (node: TemplateNode) => void;
};

export function TemplateTree({ nodes, selectedId, onSelect }: TemplateTreeProps) {
  return (
    <section className="panel tree-panel">
      <div className="panel-heading">
        <h2>模板目录树</h2>
        <span className="status">{countNodes(nodes)} 节</span>
      </div>
      <div className="tree-scroll">
        {nodes.map((node) => (
          <TreeNode key={node.id} node={node} selectedId={selectedId} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}

function TreeNode({ node, selectedId, onSelect }: { node: TemplateNode; selectedId?: string | null; onSelect: (node: TemplateNode) => void }) {
  const selected = node.id === selectedId;
  return (
    <div className="tree-node" style={{ paddingLeft: `${Math.max(0, node.level - 1) * 12}px` }}>
      <button className={selected ? "selected tree-button" : "tree-button"} onClick={() => onSelect(node)}>
        <span className="tree-title">{node.title}</span>
        {node.special_notes.length > 0 ? <span className="badge">重点</span> : null}
      </button>
      {node.children.map((child) => (
        <TreeNode key={child.id} node={child} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

function countNodes(nodes: TemplateNode[]): number {
  return nodes.reduce((total, node) => total + 1 + countNodes(node.children), 0);
}
