export type TemplateNode = {
  id: string;
  title: string;
  level: number;
  source_rules: string[];
  auto_fill: string[];
  manual_fill: string[];
  special_notes: string[];
  children: TemplateNode[];
};

export type TemplateSummary = {
  template_id: string;
  name: string;
  path?: string | null;
};

export type ProjectResponse = {
  id: string;
  project_id: string;
  name: string;
  template_id: string;
  section_count: number;
  run_count: number;
};

export type SourceTocItem = {
  section_id: string;
  title_path: string[];
  level: number;
  char_count: number;
  snippet: string;
};

export type ChapterTask = {
  node_id: string;
  title: string;
  status: string;
  source_matches: SourceMatch[];
  draft_id?: string | null;
  error_message?: string | null;
};

export type DirectoryResponse = {
  project: ProjectResponse;
  template?: { template_id: string; name: string; nodes: TemplateNode[] } | null;
  source_toc?: { items: SourceTocItem[]; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  outline?: { outline: unknown; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  chapter_tasks: ChapterTask[];
};

export type RunResponse = {
  id: string;
  run_id: string;
  status: string;
  task_count: number;
  passed_count: number;
  failed_count: number;
  final_artifact_path?: string | null;
  logs: string[];
};

export type ChapterResponse = {
  node_id: string;
  title: string;
  status: string;
  markdown: string;
  source_matches: SourceMatch[];
};

export type SourceMatch = {
  section_id: string;
  title_path: string[];
  snippet: string;
  score: number;
};

const API_BASE = import.meta.env.VITE_COALPLAN_API_BASE ?? "http://127.0.0.1:8010";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  return request<TemplateSummary[]>("/templates");
}

export async function getTemplateTree(templateId: string): Promise<TemplateNode[]> {
  const data = await request<{ nodes: TemplateNode[] }>(`/templates/${templateId}`);
  return data.nodes;
}

export async function createProject(name: string, templateId: string): Promise<ProjectResponse> {
  return request<ProjectResponse>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, template_id: templateId })
  });
}

export async function setProjectTemplate(projectId: string, templateId: string): Promise<ProjectResponse> {
  return request<ProjectResponse>(`/projects/${projectId}/template`, {
    method: "POST",
    body: JSON.stringify({ template_id: templateId })
  });
}

export async function uploadBidMarkdown(projectId: string, fileName: string, content: string): Promise<ProjectResponse> {
  return request<ProjectResponse>(`/projects/${projectId}/bid-markdown`, {
    method: "POST",
    body: JSON.stringify({ file_name: fileName, content })
  });
}

export async function generateDirectory(projectId: string): Promise<DirectoryResponse> {
  return request<DirectoryResponse>(`/projects/${projectId}/directory`, { method: "POST" });
}

export async function getDirectory(projectId: string): Promise<DirectoryResponse> {
  return request<DirectoryResponse>(`/projects/${projectId}/directory`);
}

export async function listChapters(projectId: string): Promise<ChapterTask[]> {
  return request<ChapterTask[]>(`/projects/${projectId}/chapters`);
}

export async function generateProject(projectId: string): Promise<RunResponse> {
  return request<RunResponse>(`/projects/${projectId}/generate`, { method: "POST" });
}

export async function generateChapter(projectId: string, nodeId: string): Promise<ChapterResponse> {
  return request<ChapterResponse>(`/projects/${projectId}/chapters/${nodeId}/generate`, { method: "POST" });
}

export async function getChapter(projectId: string, nodeId: string): Promise<ChapterResponse> {
  return request<ChapterResponse>(`/projects/${projectId}/chapters/${nodeId}`);
}

export async function mergeProject(projectId: string): Promise<RunResponse> {
  return request<RunResponse>(`/projects/${projectId}/merge`, { method: "POST" });
}

export async function getFinalMarkdown(projectId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/artifacts/final.md`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.text();
}
