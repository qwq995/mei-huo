import { render, screen, waitFor, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, test, vi } from "vitest"
import { OutlinePlanning } from "./OutlinePlanning"
import { ToastProvider } from "./Toast"

const { startJob } = vi.hoisted(() => ({ startJob: vi.fn(async () => ({})) }))
vi.mock("./Jobs", () => ({ useJobs: () => ({ startJob, activeJob: null, jobs: [] }) }))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); localStorage.clear() })

test("项目理解入口提交正确后台任务", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ stage: "understanding", revision: 0, stale_node_ids: [], history: [] }))))
  render(<ToastProvider><OutlinePlanning projectId="p1" nodes={[]} onChanged={() => {}} /></ToastProvider>)
  await userEvent.click(await screen.findByRole("button", { name: "读取投标资料，理解项目" }))
  await waitFor(() => expect(startJob).toHaveBeenCalledWith("outline_understand", { document_type: "organization" }))
})

test("写作任务与技巧加载为独立可编辑表单并保存", async () => {
  const contract = { node_id: "n1", scope_statement: "工程概况范围", writing_tasks: ["项目名称", "施工范围"], writing_skills: ["先概述后分项"], out_of_scope: [], interfaces: [], source_section_ids: [], missing_information: [], role: "independent" }
  const state = { stage: "blueprint", revision: 4, stale_node_ids: [], history: [], blueprint: { summary: "全书指导", contracts: [contract] } }
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(state)))
  vi.stubGlobal("fetch", fetchMock)
  render(<ToastProvider><OutlinePlanning projectId="p1" nodes={[]} onChanged={() => {}} /></ToastProvider>)
  await userEvent.click(await screen.findByRole("button", { name: "n1" }))
  const tasks = screen.getByRole("textbox", { name: "写作任务：本章写什么" })
  const skills = screen.getByRole("textbox", { name: "写作技巧：如何组织表达" })
  expect(tasks).toHaveValue("项目名称\n施工范围")
  expect(skills).toHaveValue("先概述后分项")
  await userEvent.clear(tasks)
  await userEvent.type(tasks, "工程范围")
  await userEvent.click(screen.getByRole("button", { name: "保存生成指导" }))
  await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1))
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
  const saved = JSON.parse(String(calls.find(c => c[1]?.method === "PATCH")?.[1].body))
  expect(saved.contract.writing_tasks).toEqual(["工程范围"])
  expect(saved.contract.writing_skills).toEqual(["先概述后分项"])
})
