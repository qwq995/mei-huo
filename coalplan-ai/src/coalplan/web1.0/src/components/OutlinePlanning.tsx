import { useEffect, useState, type ReactNode } from "react"
import { Check, ListTree, Pencil, RefreshCw, Send, X } from "lucide-react"
import { API_BASE, applyOutlineProposal, listOutlineProposals, getSourceSection, type OutlineNode, type AIProposal, type GenerationJobType } from "@/lib/api"
import { useJobs } from "@/components/Jobs"
import { Button, TextArea } from "@/components/ui"
import { useToast } from "@/components/Toast"

type Contract = { node_id: string; scope_statement: string; writing_tasks: string[]; writing_skills: string[]; out_of_scope: string[]; interfaces: string[]; source_section_ids: string[]; missing_information: string[]; role: string }
type State = { stage: string; revision: number; outline_fingerprint: string; stale_node_ids: string[]; sources_changed: boolean; understanding?: { overview: string; sector: string; conflicts: string[]; unknowns: string[]; recommendations: { template_id: string; name: string; top_headings: string[]; reason: string; differences: string[] }[] }; latest_proposal_id?: string; history: { message?: string; reason?: string }[]; blueprint?: { summary: string; contracts: Contract[] }; basis_registry?: { files: { file_name: string }[]; unresolved: string[] } }
const stages = [{ key: "understanding", label: "项目理解" }, { key: "skeleton", label: "一级骨架" }, { key: "expansion", label: "二级目录" }, { key: "blueprint", label: "生成指导" }]

function PlanningSources({ projectId, ids }: { projectId: string; ids: string[] }) {
  const [sources, setSources] = useState<{ title: string; file: string; content: string }[]>([])
  const [error, setError] = useState("")
  useEffect(() => {
    let active = true
    setSources([])
    void Promise.all(ids.map(id => getSourceSection(projectId, id))).then(values => {
      if (active) setSources(values.map(s => ({ title: s.title_path.join(" / "), file: s.source_file, content: s.content })))
    }).catch(() => { if (active) setError("来源读取失败，请关闭后重新打开。") })
    return () => { active = false }
  }, [projectId, ids])
  return <div className="space-y-2">{error && <p role="alert">{error}</p>}{!sources.length && !error && <p>{ids.length ? "正在读取来源…" : "暂无项目证据"}</p>}{sources.map((s, i) => <details key={i} className="border-b py-2"><summary className="cursor-pointer break-words">{s.title}</summary><p className="my-2 break-words text-xs text-muted-foreground">{s.file}</p><div className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words leading-6">{s.content}</div></details>)}</div>
}

async function planningRequest<T>(projectId: string, suffix = "", body?: unknown, method = "POST"): Promise<T> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/outline/planning${suffix}`, body === undefined ? undefined : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  if (!response.ok) { const error = await response.json(); throw new Error(typeof error.detail === "string" ? error.detail : "规划操作失败") }
  return response.json()
}

function PlanningWindow({ title, children, close }: { title: string; children: ReactNode; close: () => void }) {
  useEffect(() => { const handler = (event: KeyboardEvent) => { if (event.key === "Escape") close() }; document.addEventListener("keydown", handler); return () => document.removeEventListener("keydown", handler) }, [close])
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 p-3" role="presentation"><section role="dialog" aria-modal="true" aria-label={title} className="flex max-h-[90dvh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border bg-card shadow-xl"><header className="flex items-center justify-between border-b p-4"><h2 className="font-semibold">{title}</h2><Button variant="ghost" size="icon" aria-label="关闭" onClick={close}><X size={18} /></Button></header><div className="overflow-y-auto p-4">{children}</div></section></div>
}

export function OutlinePlanning({ projectId, nodes, onChanged, onPlanningActive }: { projectId: string; nodes: OutlineNode[]; onChanged: () => void; onPlanningActive?: (active: boolean) => void }) {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState("")
  const [view, setView] = useState("understanding")
  const [sector, setSector] = useState("")
  const [documentType, setDocumentType] = useState("organization")
  const [message, setMessage] = useState(() => localStorage.getItem(`outline-chat:${projectId}`) ?? "")
  const [rootId, setRootId] = useState("")
  const [proposal, setProposal] = useState<AIProposal | null>(null)
  const [contract, setContractState] = useState<Contract | null>(null)
  const setContract = (next: Contract | null) => setContractState(next ? {
    ...next,
    interfaces: next.interfaces.map(text => nodes.reduce((value, node) => value.split(node.node_id).join(node.title), text)),
  } : null)
  const [excluded, setExcluded] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const { activeJob, startJob, jobs } = useJobs()
  const toast = useToast()
  const blocked = busy || Boolean(activeJob)
  const reload = async () => {
    try { const next = await planningRequest<State>(projectId); setState(next); setError(""); return next }
    catch (e) { setError(e instanceof Error ? e.message : "无法读取规划"); return null }
  }
  useEffect(() => { setMessage(localStorage.getItem(`outline-chat:${projectId}`) ?? ""); void reload().then(s => s && setView(s.stage === "ready" ? "blueprint" : s.stage)) }, [projectId])
  useEffect(() => { const handle = (event: Event) => { if ((event as CustomEvent).detail?.project_id === projectId) { void reload(); onChanged() } }; window.addEventListener("coalplan:job-finished", handle); return () => window.removeEventListener("coalplan:job-finished", handle) }, [projectId])
  useEffect(() => { localStorage.setItem(`outline-chat:${projectId}`, message) }, [projectId, message])
  useEffect(() => { void reload() }, [nodes])
  useEffect(() => { onPlanningActive?.(Boolean(state && state.revision > 0)) }, [state?.revision, onPlanningActive])
  const reopen = async () => {
    if (!state) return
    setBusy(true)
    try { const next = await planningRequest<State>(projectId, "/confirm", { stage: "reopen", revision: state.revision }); setState(next); setView(next.stage) }
    catch (e) { toast.error(e instanceof Error ? e.message : "无法重新确认目录") } finally { setBusy(false) }
  }
  const run = async (type: GenerationJobType, payload = {}) => { setBusy(true); try { await startJob(type, payload) } catch (e) { toast.error(e instanceof Error ? e.message : "任务提交失败") } finally { setBusy(false) } }
  const confirm = async () => {
    if (!state) return
    setBusy(true)
    try { const next = await planningRequest<State>(projectId, "/confirm", { stage: state.stage, revision: state.revision, outline_fingerprint: state.outline_fingerprint, sector: sector || undefined }); setState(next); setView(next.stage === "ready" ? "blueprint" : next.stage); onChanged(); toast.success("已确认并保存") }
    catch (e) { toast.error(e instanceof Error ? e.message : "确认失败") } finally { setBusy(false) }
  }
  const preview = async () => { try { const proposals = await listOutlineProposals(projectId); const current = proposals.find(p => p.id === state?.latest_proposal_id); if (!current) throw new Error("当前提案已处理，请查看目录或重新生成建议"); setProposal(current); setExcluded([]) } catch (e) { toast.error(e instanceof Error ? e.message : "无法读取提案") } }
  const apply = async () => { if (!proposal) return; setBusy(true); try { await applyOutlineProposal(projectId, proposal.id, { exclude_node_ids: excluded }); setProposal(null); await reload(); onChanged(); toast.success("目录修改已应用，可在目录提案中撤销") } catch (e) { toast.error(e instanceof Error ? e.message : "应用失败") } finally { setBusy(false) } }
  const save = async () => { if (!state || !contract) return; setBusy(true); try { const next = await planningRequest<State>(projectId, `/contracts/${contract.node_id}`, { revision: state.revision, contract }, "PATCH"); setState(next); setContract(null); toast.success("已保存，确认生成指导后用于正文") } catch (e) { toast.error(e instanceof Error ? e.message : "保存失败") } finally { setBusy(false) } }
  const latestFailed = jobs.find(j => j.job_type.startsWith("outline_") && j.status === "failed")
  return <section className="min-w-0 border-b pb-4" aria-label="分阶段目录规划">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="flex items-center gap-2 text-base font-semibold"><ListTree size={18} />目录规划</h2><Button variant="ghost" size="icon" title="刷新规划" aria-label="刷新规划" onClick={() => void reload()}><RefreshCw size={16} /></Button></div>
    <nav className="my-3 grid grid-cols-2 gap-1 sm:grid-cols-4" aria-label="规划阶段">{stages.map((s, i) => <button key={s.key} onClick={() => setView(s.key)} aria-current={view === s.key ? "step" : undefined} className={`border-b-2 px-2 py-2 text-sm ${view === s.key ? "border-primary font-semibold text-primary" : "border-transparent text-muted-foreground"}`}>{i + 1}. {s.label}</button>)}</nav>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {state && ["blueprint", "ready"].includes(state.stage) && <Button size="sm" variant="ghost" disabled={blocked} onClick={() => void reopen()}>目录有调整，重新确认</Button>}
    {activeJob && <p role="status" className="mb-3 text-sm text-primary">{activeJob.message}</p>}
    {latestFailed && <details className="mb-2 text-sm text-red-700"><summary>最近一次规划未完成，可在任务中心重试</summary>{latestFailed.error}</details>}
    {(state?.sources_changed || state?.stale_node_ids.length) ? <p className="mb-2 text-sm text-amber-700">资料或章节发生变化，相关生成指导需要更新。</p> : null}
    {view === "understanding" && <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3"><label className="text-sm">成果类型 <select aria-label="成果类型" className="rounded border bg-card p-2" value={documentType} onChange={e => setDocumentType(e.target.value)}><option value="organization">综合施工组织设计</option><option value="special">专项施工方案</option></select></label><Button disabled={blocked} icon={<RefreshCw size={16} />} onClick={() => void run("outline_understand", { document_type: documentType })}>{state?.understanding ? "重新理解项目" : "读取投标资料，理解项目"}</Button></div>
      {state?.understanding && <><p className="whitespace-pre-wrap text-sm leading-6">{state.understanding.overview}</p><label className="block text-sm">专业归口 <select aria-label="专业归口" value={sector || state.understanding.sector} onChange={e => setSector(e.target.value)} className="rounded border bg-card p-2"><option value="unknown">待确认</option><option value="power">电力建设工程</option><option value="water">水利工程</option><option value="road">公路工程</option><option value="building">房建市政工程</option></select></label>{[...(state.understanding.conflicts ?? []), ...(state.understanding.unknowns ?? [])].map((x, i) => <p key={i} className="text-sm text-amber-700">{typeof x === "string" ? x : JSON.stringify(x)}</p>)}</>}
    </div>}
    {view === "skeleton" && <div className="grid gap-3 md:grid-cols-3">{state?.understanding?.recommendations.map(t => <article key={t.template_id} className="min-w-0 rounded-lg border p-3"><h3 className="text-sm font-semibold">{t.name}</h3><p className="my-2 text-xs leading-5 text-muted-foreground">{t.reason}</p><details><summary className="cursor-pointer text-sm text-primary">查看一级目录与差异</summary><ol className="my-2 space-y-1 text-sm">{t.top_headings.map((x, i) => <li key={i}>{x}</li>)}</ol>{t.differences.map((x, i) => <p className="text-xs" key={i}>{x}</p>)}</details><Button className="mt-3" size="sm" disabled={blocked || state.stage !== "skeleton"} onClick={() => void run("outline_skeleton", { template_id: t.template_id })}>预览采用此模板</Button></article>)}{!state?.understanding && <p className="text-sm text-muted-foreground">请先完成项目理解。</p>}</div>}
    {view === "expansion" && <div className="flex flex-wrap gap-2"><select aria-label="待扩充一级章节" className="min-w-0 max-w-full rounded border bg-card p-2 text-sm" value={rootId} onChange={e => setRootId(e.target.value)}><option value="">选择一级章节</option>{nodes.filter(n => !n.parent_id && n.enabled !== false).map(n => <option key={n.node_id} value={n.node_id}>{n.title}</option>)}</select><Button disabled={blocked || !rootId || state?.stage !== "expansion"} onClick={() => void run("outline_expand", { node_id: rootId })}>扩充二级目录</Button></div>}
    {view === "blueprint" && <div className="space-y-3"><Button disabled={blocked || !["blueprint", "ready"].includes(state?.stage ?? "")} onClick={() => void run("outline_blueprint")}>生成全书指导</Button>{state?.blueprint && <><p className="text-sm leading-6">{state.blueprint.summary}</p><div className="max-h-64 divide-y overflow-y-auto">{state.blueprint.contracts.map(c => <button key={c.node_id} className="flex w-full items-center justify-between gap-2 py-2 text-left text-sm hover:bg-muted" onClick={() => setContract(structuredClone(c))}><span className="min-w-0 break-words">{nodes.find(n => n.node_id === c.node_id)?.title ?? c.node_id}</span><Pencil size={15} className="shrink-0" /></button>)}</div></>}{state?.stage === "ready" && <Button disabled={blocked} variant="outline" onClick={() => void run("outline_basis")}>正文完成后汇总编制依据</Button>}{state?.basis_registry && <details><summary>查看依据文件台账</summary>{state.basis_registry.files.map(f => <p className="text-sm" key={f.file_name}>{f.file_name}</p>)}{state.basis_registry.unresolved.map((x, i) => <p className="text-sm text-amber-700" key={i}>待核对：{x}</p>)}</details>}</div>}
    {state && state.stage !== "understanding" && <div className="mt-4 space-y-2"><label htmlFor="outline-dialogue" className="text-sm font-medium">对话调整目录</label><div className="flex items-end gap-2"><TextArea id="outline-dialogue" value={message} rows={2} placeholder="例如：增加隧洞排水，将设备配置放到资源计划中" onChange={e => setMessage(e.target.value)} /><Button title="提交修改要求" aria-label="提交修改要求" size="icon" disabled={blocked || !message.trim()} onClick={() => void run("outline_chat", { suggestion: message })}><Send size={16} /></Button></div><details><summary className="cursor-pointer text-xs text-muted-foreground">历史调整</summary>{state.history.filter(h => h.message).map((h, i) => <p className="my-2 text-sm" key={i}>{h.message}<br />{h.reason}</p>)}</details></div>}
    <footer className="mt-3 flex flex-wrap gap-2">{state?.latest_proposal_id && <Button variant="outline" size="sm" onClick={() => void preview()}>查看目录变更</Button>}{state && state.stage !== "ready" && state.stage === view && <Button size="sm" disabled={blocked || (view === "understanding" && !state.understanding)} icon={<Check size={15} />} onClick={() => void confirm()}>{view === "blueprint" ? "确认指导，进入生成" : "确认本阶段"}</Button>}</footer>
    {proposal && <PlanningWindow title="核对目录变更后应用" close={() => setProposal(null)}><div className="space-y-3">{((proposal.preview.nodes ?? []) as Record<string, unknown>[]).map((p: Record<string, unknown>) => { const id = String(p.node_id); const before = nodes.find(n => n.node_id === id); return <div key={id} className="border-b pb-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!excluded.includes(id)} onChange={e => setExcluded(e.target.checked ? excluded.filter(x => x !== id) : [...excluded, id])} />保留此变更</label><div className="mt-2 grid gap-2 sm:grid-cols-2"><div className="min-w-0 break-words bg-muted p-2 text-sm">当前：{before?.title ?? "无此节点"}<p>{before?.auto_fill?.join("；")}</p></div><div className="min-w-0 break-words border p-2 text-sm">修改后：{p.enabled === false ? "禁用 " : ""}{String(p.title ?? before?.title ?? "")}<p>{Array.isArray(p.auto_fill) ? p.auto_fill.join("；") : ""}</p></div></div>{before?.selected_version_id && <p className="mt-1 text-xs text-amber-700">此章节已有正文版本，将保留历史记录。</p>}</div> })}<Button disabled={blocked} onClick={() => void apply()}>应用所选变更</Button></div></PlanningWindow>}
    {contract && <PlanningWindow title={`生成指导 · ${nodes.find(n => n.node_id === contract.node_id)?.title ?? "本章"}`} close={() => setContract(null)}><div className="grid gap-4 sm:grid-cols-2">{([{ key: "writing_tasks", label: "写作任务：本章写什么" }, { key: "writing_skills", label: "写作技巧：如何组织表达" }, { key: "out_of_scope", label: "本章不写的内容" }, { key: "interfaces", label: "与其他章节的接口" }] as const).map(f => <label key={f.key} className="space-y-1 text-sm">{f.label}<TextArea rows={5} value={contract[f.key].join("\n")} onChange={e => setContract({ ...contract, [f.key]: e.target.value.split("\n") })} /></label>)}<label className="text-sm sm:col-span-2">章节范围<TextArea value={contract.scope_statement} onChange={e => setContract({ ...contract, scope_statement: e.target.value })} /></label></div><details className="my-3 text-sm"><summary>来源与待补信息</summary><PlanningSources projectId={projectId} ids={contract.source_section_ids} />{contract.missing_information.map((x, i) => <p key={i}>{x}</p>)}</details><Button disabled={blocked} onClick={() => void save()}>保存生成指导</Button></PlanningWindow>}
  </section>
}
