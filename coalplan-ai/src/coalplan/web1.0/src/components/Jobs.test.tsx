import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"
import { JobsProvider, TaskCenter } from "@/components/Jobs"
import { ToastProvider } from "@/components/Toast"
const { failedJob, retryGenerationJob } = vi.hoisted(() => {
  const failedJob = {
    job_id: "job_1", project_id: "p1", job_type: "chapter_generation" as const, status: "failed" as const, stage: "failed",
    current: 1, total: 3, message: "任务执行失败，可查看详情后重试", payload: { node_id: "n1" }, result: {},
    error: "模型请求超时", created_at: "2026-08-03T10:00:00", updated_at: "2026-08-03T10:01:00",
  }
  return { failedJob, retryGenerationJob: vi.fn(async () => ({ ...failedJob, job_id: "job_2", status: "queued" as const, error: null })) }
})
vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  listGenerationJobs: vi.fn(async () => [failedJob]),
  retryGenerationJob,
  createGenerationJob: vi.fn(),
}))

test("任务中心展示失败详情并允许重试", async () => {
  const user = userEvent.setup()
  render(<ToastProvider><JobsProvider projectId="p1"><TaskCenter /></JobsProvider></ToastProvider>)
  await user.click(await screen.findByRole("button", { name: /1 项待处理/ }))
  expect(screen.getByText("任务执行失败，可查看详情后重试")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "重试任务" }))
  await waitFor(() => expect(retryGenerationJob).toHaveBeenCalledWith("p1", "job_1"))
})
