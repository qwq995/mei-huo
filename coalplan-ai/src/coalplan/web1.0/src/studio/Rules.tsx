import { useEffect, useState } from "react";
import * as A from "@/lib/api";
import { useToast } from "@/components/Toast";
import {
  api,
  Document,
  Filter,
  Modal,
  Status,
  useResource,
  statusName,
} from "./common";

type Standard = {
  id: string;
  name: string;
  standard_code: string;
  category: string;
  atom_count: number;
};
type Clause = {
  id: string;
  clause_no: string;
  source_text: string;
  normalized_requirement: string;
  applicability: string[];
  status: string;
};
export function Rules({ kind }: { kind: "skills" | "standards" }) {
  const skills = useResource(A.getPatternLibrary, []),
    standards = useResource(() => api<Standard[]>("/standards/documents"), []),
    [query, setQuery] = useState(""),
    [skill, setSkill] = useState<A.WritingPattern | null>(null),
    [clauses, setClauses] = useState<Clause[] | null>(null);
  const toast = useToast();
  return (
    <>
      <div className="s-toolbar">
        <Filter
          value={query}
          change={setQuery}
          placeholder={
            kind === "skills" ? "搜索写作技巧" : "搜索规范名称或编号"
          }
        />
        <span className="s-badge">
          {kind === "skills" ? "组织表达规则" : "审查依据"}
        </span>
      </div>
      {kind === "skills" ? (
        <>
          <Status {...skills} retry={skills.reload} />
          {Object.values(skills.data?.library.patterns || {})
            .filter((s) => (s.aliases.join(" ") + s.key).includes(query))
            .map((s) => (
              <button
                className="s-list-row"
                key={s.key}
                onClick={() => setSkill(s)}
              >
                <span>
                  {s.aliases[0] || s.key}
                  <small>{s.preferred_structure.join(" · ")}</small>
                </span>
                <span>查看规则</span>
              </button>
            ))}
          <p className="s-muted">
            项目内可编辑本章技巧；全局技巧编辑入口开发中。
          </p>
        </>
      ) : (
        <>
          <Status {...standards} retry={standards.reload} />
          {standards.data
            ?.filter((s) => (s.name + s.standard_code).includes(query))
            .map((s) => (
              <button
                className="s-list-row"
                key={s.id}
                onClick={async () => {
                  try {
                    setClauses(
                      await api<Clause[]>(
                        `/standards/documents/${s.id}/constraints`,
                      ),
                    );
                  } catch (e) {
                    toast.error((e as Error).message);
                  }
                }}
              >
                <span>
                  {s.name}
                  <small>
                    {s.standard_code} · {s.category}
                  </small>
                </span>
                <span>{s.atom_count} 条</span>
              </button>
            ))}
        </>
      )}
      {skill && (
        <Modal
          title={skill.aliases[0] || skill.key}
          close={() => setSkill(null)}
        >
          {(
            [
              ["preferred_structure", "推荐结构"],
              ["auto_writable_moves", "组织与展开"],
              ["required_source_facts", "所需项目事实"],
              ["human_only_items", "需人工确认"],
            ] as const
          ).map(([key, label]) => (
            <section key={key}>
              <h3>{label}</h3>
              {skill[key].map((x, i) => (
                <p key={i}>{x}</p>
              ))}
            </section>
          ))}
        </Modal>
      )}
      {clauses && (
        <Modal wide title="规范审查条例" close={() => setClauses(null)}>
          {clauses.length ? (
            clauses.map((c) => (
              <details key={c.id} className="s-band">
                <summary>
                  {c.clause_no} · {c.normalized_requirement}{" "}
                  <span className="s-badge">{statusName(c.status)}</span>
                </summary>
                <Document text={c.source_text} />
                <p>适用条件：{c.applicability.join("；") || "未标注"}</p>
              </details>
            ))
          ) : (
            <p>此文档尚无可查看的条例。</p>
          )}
        </Modal>
      )}
    </>
  );
}
type Finding = {
  id: string;
  chapter_title: string;
  standard_name: string;
  clause_no: string;
  explanation: string;
  suggested_fix: string;
  constraint_text: string;
  evidence_quote: string;
  status: string;
};
export function ReviewResults({ projectId }: { projectId: string }) {
  const resource = useResource(
    () => api<Finding[]>(`/standards/projects/${projectId}/findings`),
    [projectId],
  );
  useEffect(() => {
    const refresh = () => resource.reload();
    window.addEventListener("coalplan:job-finished", refresh);
    return () => window.removeEventListener("coalplan:job-finished", refresh);
  }, [projectId]);
  return (
    <section className="s-band">
      <div className="s-toolbar">
        <h2>审查问题</h2>
        <button onClick={resource.reload}>刷新结果</button>
      </div>
      <Status {...resource} retry={resource.reload} />
      {resource.data?.length
        ? resource.data.map((f) => (
            <details key={f.id} className="s-band">
              <summary>
                {f.chapter_title} · {f.standard_name} {f.clause_no}
              </summary>
              <h3>审查结论</h3>
              <p>{f.explanation}</p>
              <h3>建议处理</h3>
              <p>{f.suggested_fix || "请核对原文与适用条件"}</p>
              <h3>对应条例</h3>
              <Document text={f.constraint_text} />
              <h3>正文引用</h3>
              <Document text={f.evidence_quote} />
              <p className="s-muted">状态：{f.status}</p>
            </details>
          ))
        : !resource.loading && (
            <p className="s-muted">暂无审查问题记录，不代表已通过审查。</p>
          )}
    </section>
  );
}
