import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { Document, Modal, useResource } from "./common";
import { Projects } from "./WorkspacePages";
import { ToastProvider } from "@/components/Toast";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
test("Markdown previews do not execute uploaded HTML", () => {
  const { container } = render(
    <Document
      text={'# Title\n<img src=x onerror="alert(1)"><script>bad()</script>'}
    />,
  );
  expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
  expect(container.querySelector("script,img")).toBeNull();
});
test("modal delegates keyboard focus to native dialog and has a clear close action", async () => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  const close = vi.fn();
  render(
    <Modal title="核对版本" close={close}>
      <button>确认选用</button>
    </Modal>,
  );
  expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalledOnce();
  await userEvent.click(
    screen.getByRole("button", { name: "关闭窗口", hidden: true }),
  );
  expect(close).toHaveBeenCalledOnce();
});
test("late responses cannot replace a different page resource", async () => {
  let oldResolve: (v: string) => void = () => {};
  const old = new Promise<string>((resolve) => {
    oldResolve = resolve;
  });
  function Probe({ id }: { id: string }) {
    const r = useResource(
      () => (id === "old" ? old : Promise.resolve("new data")),
      [id],
    );
    return <span>{r.data}</span>;
  }
  const view = render(<Probe id="old" />);
  view.rerender(<Probe id="new" />);
  await screen.findByText("new data");
  oldResolve("old data");
  await waitFor(() => expect(screen.queryByText("old data")).toBeNull());
});
test("project search and entry operate on actual project identifiers", async () => {
  const select = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (input: string) =>
        new Response(
          JSON.stringify(
            input.endsWith("/templates")
              ? [{ template_id: "road", name: "公路" }]
              : [
                  {
                    project_id: "p-road",
                    name: "复建公路",
                    source_document_count: 1,
                    section_count: 4,
                  },
                  {
                    project_id: "p-water",
                    name: "水利工程",
                    source_document_count: 2,
                    section_count: 8,
                  },
                ],
          ),
        ),
    ),
  );
  render(
    <ToastProvider>
      <Projects select={select} />
    </ToastProvider>,
  );
  await screen.findByText("复建公路");
  await userEvent.type(
    screen.getByRole("textbox", { name: "搜索项目名称" }),
    "公路",
  );
  expect(screen.queryByText("水利工程")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "进入工作台" }));
  expect(select).toHaveBeenCalledWith(
    expect.objectContaining({ project_id: "p-road" }),
  );
});
