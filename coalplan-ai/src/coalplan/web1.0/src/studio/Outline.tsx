import { useState } from "react";
import {
  ArrowRight,
  ArrowUp,
  ArrowDown,
  Plus,
  Pencil,
  Trash2,
  History,
} from "lucide-react";
import * as A from "@/lib/api";
import { OutlinePlanning } from "@/components/OutlinePlanning";
import { useToast } from "@/components/Toast";
import { useJobs } from "@/components/Jobs";
import { Filter, Modal, Status, useResource } from "./common";

export function Outline({
  project,
  next,
}: {
  project: A.ProjectResponse;
  next: () => void;
}) {
  const nodes = useResource(
      () => A.listOutlineNodes(project.project_id),
      [project.project_id],
    ),
    [query, setQuery] = useState(""),
    [edit, setEdit] = useState<A.OutlineNode | null>(null),
    [initial, setInitial] = useState(""),
    [busy, setBusy] = useState(false),
    [proposals, setProposals] = useState<A.AIProposal[] | null>(null),
    [proposal, setProposal] = useState<A.AIProposal | null>(null),
    [snapshot, setSnapshot] = useState("");
  const { activeJob } = useJobs(),
    toast = useToast();
  const blocked = busy || Boolean(activeJob);
  const action = async (f: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await f();
      nodes.reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const close = () => {
    if (
      edit &&
      JSON.stringify(edit) !== initial &&
      !confirm("目录修改尚未保存，是否放弃本次修改？")
    )
      return;
    setEdit(null);
  };
  const list = nodes.data || [];
  return (
    <>
      <div className="s-toolbar">
        <span className="s-subtitle">确认前可编辑目录与章节任务</span>
        <button className="primary" onClick={next}>
          进入章节编写
          <ArrowRight size={16} />
        </button>
      </div>
      <details className="s-planning" open={!list.length}>
        <summary>分阶段规划与 AI 对话</summary>
        <OutlinePlanning
          projectId={project.project_id}
          nodes={list}
          onChanged={nodes.reload}
        />
      </details>
      <div className="s-toolbar">
        <Filter value={query} change={setQuery} placeholder="搜索目录标题" />
        <div className="s-actions">
          <button
            onClick={async () => {
              try {
                setProposals(await A.listOutlineProposals(project.project_id));
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            <History size={16} />
            待审变更
          </button>
          <button
            disabled={blocked}
            onClick={() => {
              const n = {
                id: String(Date.now()),
                node_id: "",
                title: "",
                level: 1,
                parent_id: null,
                enabled: true,
                source_rules: [],
                auto_fill: [],
                manual_fill: [],
                special_notes: [],
                source_hints: [],
              } as A.OutlineNode;
              setInitial(JSON.stringify(n));
              setEdit(n);
            }}
          >
            <Plus size={16} />
            新增章节
          </button>
        </div>
      </div>
      <Status {...nodes} retry={nodes.reload} />
      {snapshot && (
        <div className="s-notice">
          目录变更已应用
          <button
            onClick={() =>
              void action(async () => {
                await A.restoreOutlineSnapshot(project.project_id, snapshot);
                setSnapshot("");
              })
            }
          >
            撤销本次变更
          </button>
        </div>
      )}
      <div className="s-outline">
        <div className="s-outline-head">
          <span>章节结构</span>
          <span>写作任务</span>
          <span>操作</span>
        </div>
        {list
          .filter((n) => n.title.includes(query))
          .map((n) => (
            <div className="s-outline-row" key={n.node_id}>
              <button
                className="s-node-title"
                style={{ paddingLeft: Math.min(n.level - 1, 5) * 16 + 8 }}
                onClick={() => {
                  setInitial(JSON.stringify(n));
                  setEdit(structuredClone(n));
                }}
              >
                <span
                  className={`s-node-dot ${n.enabled === false ? "off" : ""}`}
                />
                {n.title}
              </button>
              <span className="s-outline-task">
                {n.auto_fill?.join("；") || "待设置"}
              </span>
              <div className="s-row-actions">
                <button
                  className="s-icon"
                  title="编辑章节"
                  aria-label={`编辑 ${n.title}`}
                  onClick={() => {
                    setInitial(JSON.stringify(n));
                    setEdit(structuredClone(n));
                  }}
                >
                  <Pencil size={16} />
                </button>
                <button
                  className="s-icon"
                  disabled={blocked}
                  title="上移"
                  aria-label={`上移 ${n.title}`}
                  onClick={() =>
                    void action(() =>
                      A.moveOutlineNode(project.project_id, n.node_id, "up"),
                    )
                  }
                >
                  <ArrowUp size={15} />
                </button>
                <button
                  className="s-icon"
                  disabled={blocked}
                  title="下移"
                  aria-label={`下移 ${n.title}`}
                  onClick={() =>
                    void action(() =>
                      A.moveOutlineNode(project.project_id, n.node_id, "down"),
                    )
                  }
                >
                  <ArrowDown size={15} />
                </button>
              </div>
            </div>
          ))}
      </div>
      {edit && (
        <Modal
          title={edit.node_id ? "编辑目录章节" : "新增目录章节"}
          close={close}
        >
          <label>
            章节标题
            <input
              autoFocus
              value={edit.title}
              onChange={(e) => setEdit({ ...edit, title: e.target.value })}
            />
          </label>
          <div className="s-form-grid">
            <label>
              目标字数
              <input
                type="number"
                min="0"
                value={edit.target_word_count ?? ""}
                onChange={(e) =>
                  setEdit({
                    ...edit,
                    target_word_count: Number(e.target.value) || null,
                  })
                }
              />
            </label>
            <label>
              状态
              <select
                value={edit.enabled === false ? "off" : "on"}
                onChange={(e) =>
                  setEdit({ ...edit, enabled: e.target.value === "on" })
                }
              >
                <option value="on">启用</option>
                <option value="off">禁用</option>
              </select>
            </label>
          </div>
          <label>
            本章写作任务
            <textarea
              rows={7}
              value={edit.auto_fill?.join("\n") || ""}
              onChange={(e) =>
                setEdit({ ...edit, auto_fill: e.target.value.split("\n") })
              }
            />
          </label>
          <label>
            特殊要求
            <textarea
              rows={3}
              value={edit.special_notes?.join("\n") || ""}
              onChange={(e) =>
                setEdit({ ...edit, special_notes: e.target.value.split("\n") })
              }
            />
          </label>
          <div className="s-dialog-actions">
            {edit.node_id && (
              <button
                className="danger"
                disabled={blocked}
                onClick={() => {
                  const count = list.filter(
                    (n) => n.parent_id === edit.node_id,
                  ).length;
                  if (
                    confirm(
                      `删除“${edit.title}”及其子结构？包含 ${count} 个直接子节点，已有正文不会合入当前目录。`,
                    )
                  )
                    void action(async () => {
                      await A.deleteOutlineNode(
                        project.project_id,
                        edit.node_id,
                      );
                      setEdit(null);
                    });
                }}
              >
                <Trash2 size={16} />
                删除子树
              </button>
            )}
            <button onClick={close}>取消</button>
            <button
              className="primary"
              disabled={blocked || !edit.title.trim()}
              onClick={() =>
                void action(async () => {
                  if (edit.node_id)
                    await A.updateOutlineNode(
                      project.project_id,
                      edit.node_id,
                      edit,
                    );
                  else await A.createOutlineNode(project.project_id, edit);
                  setEdit(null);
                  toast.success("目录已保存");
                })
              }
            >
              保存目录
            </button>
          </div>
        </Modal>
      )}
      {proposals && (
        <Modal title="待审目录变更" close={() => setProposals(null)}>
          {proposals.length ? (
            proposals.map((p) => (
              <button
                className="s-list-row"
                key={p.id}
                onClick={() => {
                  setProposal(p);
                  setProposals(null);
                }}
              >
                {p.suggestion}
                <ArrowRight size={16} />
              </button>
            ))
          ) : (
            <p>没有待审的 AI 变更。</p>
          )}
        </Modal>
      )}
      {proposal && (
        <Modal wide title="核对目录版本" close={() => setProposal(null)}>
          <div className="s-compare">
            <section>
              <h3>当前目录</h3>
              {list.map((n) => (
                <p key={n.node_id} style={{ paddingLeft: (n.level - 1) * 12 }}>
                  {n.title}
                </p>
              ))}
            </section>
            <section>
              <h3>候选变更</h3>
              {((proposal.preview.nodes || []) as Partial<A.OutlineNode>[]).map(
                (n, i) => (
                  <div key={i} className="s-change">
                    <strong>
                      {n.enabled === false ? "禁用：" : ""}
                      {n.title ||
                        list.find((x) => x.node_id === n.node_id)?.title}
                    </strong>
                    <p>{n.auto_fill?.join("；")}</p>
                  </div>
                ),
              )}
            </section>
          </div>
          <div className="s-dialog-actions">
            <button
              disabled={blocked}
              onClick={() =>
                void action(async () => {
                  await A.rejectOutlineProposal(
                    project.project_id,
                    proposal.id,
                  );
                  setProposal(null);
                })
              }
            >
              不采用
            </button>
            <button
              className="primary"
              disabled={blocked}
              onClick={() =>
                void action(async () => {
                  const r = await A.applyOutlineProposal(
                    project.project_id,
                    proposal.id,
                  );
                  setSnapshot(r.snapshot_id || "");
                  setProposal(null);
                })
              }
            >
              确认采用变更
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
