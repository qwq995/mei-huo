import { createRoot } from "react-dom/client";
import { ToastProvider } from "@/components/Toast";
import "../index.css";
import "./studio.css";
import { Studio } from "./Studio";

document.documentElement.classList.add("studio-root");
createRoot(document.getElementById("root")!).render(
  <ToastProvider>
    <Studio />
  </ToastProvider>,
);
