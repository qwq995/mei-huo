import { render, screen } from "@testing-library/react"
import { expect, test, vi } from "vitest"
import App from "@/App"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  getProject: vi.fn(async () => ({ id: "p1", project_id: "p1", name: "恢复项目", template_id: "coal_fire", source_document_count: 1, section_count: 4, run_count: 0 })),
  getProjectExperienceSummary: vi.fn(async () => ({ project_id: "p1", stage: "outline", headline: "目录待确认", progress: { source_documents: 1, indexed_sections: 4, outline_nodes: 0 }, reference_library: { published_atoms: 0, total_atoms: 0, message: "" }, actions: [], principles: [] })),
  listOutlineNodes: vi.fn(async () => []),
  listGenerationJobs: vi.fn(async () => []),
}))

test("刷新后从 URL 恢复项目和当前步骤", async () => {
  window.history.replaceState({}, "", "/?project=p1&step=outline")
  render(<App />)
  expect(await screen.findByRole("heading", { name: "目录树" })).toBeInTheDocument()
  expect(screen.getByText("恢复项目")).toBeInTheDocument()
})
