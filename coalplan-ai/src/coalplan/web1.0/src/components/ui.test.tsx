import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"
import { ConfirmDialog } from "@/components/ui"

test("危险操作必须经过确认框", async () => {
  const user = userEvent.setup()
  const confirm = vi.fn()
  render(<ConfirmDialog open title="删除目录节点？" description="节点及下级目录将被删除" danger onConfirm={confirm} onClose={() => undefined} />)
  expect(screen.getByRole("dialog")).toHaveTextContent("节点及下级目录将被删除")
  await user.click(screen.getByRole("button", { name: "确认" }))
  expect(confirm).toHaveBeenCalledOnce()
})
