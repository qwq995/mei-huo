export type TemplateNode = {
  id: string;
  node_id?: string;
  parent_id?: string | null;
  title: string;
  level: number;
  sort_order?: number;
  enabled?: boolean;
  source_rules: string[];
  auto_fill: string[];
  manual_fill: string[];
  special_notes: string[];
  selected_version_id?: string | null;
  children: TemplateNode[];
};

export type OutlineNode = Omit<TemplateNode, "children"> & { node_id: string; children?: TemplateNode[] };

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
  source_document_count: number;
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

export type SourceMatch = {
  section_id: string;
  title_path: string[];
  snippet: string;
  score: number;
};

export type ChapterTask = {
  node_id: string;
  title: string;
  status: string;
  source_matches: SourceMatch[];
  draft_id?: string | null;
  error_message?: string | null;
};

export type ChapterSupplement = {
  id: string;
  kind: string;
  title: string;
  content: string;
  must_include: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ChapterAttachment = {
  id: string;
  file_name: string;
  content_type: string;
  artifact_path: string;
  description: string;
  created_at: string;
};

export type ChapterVersion = {
  id: string;
  node_id: string;
  version_no: number;
  source_type: string;
  title: string;
  markdown: string;
  artifact_path?: string | null;
  source_section_ids: string[];
  supplement_ids: string[];
  created_by: string;
  status: string;
  created_at: string;
};

export type AIProposal = {
  id: string;
  target_type: string;
  target_id: string;
  suggestion: string;
  preview: Record<string, unknown>;
  status: string;
  created_at: string;
  applied_at?: string | null;
};

export type ChapterWorkspace = {
  outline_node: OutlineNode;
  supplements: ChapterSupplement[];
  attachments: ChapterAttachment[];
  versions: ChapterVersion[];
  selected_version_id?: string | null;
  proposals: AIProposal[];
};

export type DirectoryResponse = {
  project: ProjectResponse;
  template?: { template_id: string; name: string; nodes: TemplateNode[] } | null;
  source_toc?: { items: SourceTocItem[]; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  outline?: { outline: unknown; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  chapter_tasks: ChapterTask[];
  profile_status: string;
  outline_status: string;
  outline_source: string;
  warnings: string[];
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
  version?: ChapterVersion | null;
};

export const API_BASE = import.meta.env.VITE_COALPLAN_API_BASE ?? "http://127.0.0.1:8010";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) throw new Error((await response.text()) || `${response.status} ${response.statusText}`);
  return (await response.json()) as T;
}

export const listTemplates = () => request<TemplateSummary[]>("/templates");
export const getTemplateTree = async (templateId: string) => (await request<{ nodes: TemplateNode[] }>(`/templates/${templateId}`)).nodes;
export const listProjects = () => request<ProjectResponse[]>("/projects");
export const createProject = (name: string, templateId: string) => request<ProjectResponse>("/projects", { method: "POST", body: JSON.stringify({ name, template_id: templateId }) });
export const deleteProject = (projectId: string) => request<{ deleted: boolean }>(`/projects/${projectId}`, { method: "DELETE" });
export const uploadBidMarkdown = (projectId: string, fileName: string, content: string) => request<ProjectResponse>(`/projects/${projectId}/bid-markdown`, { method: "POST", body: JSON.stringify({ file_name: fileName, content }) });
export const generateDirectory = (projectId: string) => request<DirectoryResponse>(`/projects/${projectId}/directory`, { method: "POST" });
export const getDirectory = (projectId: string) => request<DirectoryResponse>(`/projects/${projectId}/directory`);
export const listOutlineNodes = (projectId: string) => request<OutlineNode[]>(`/projects/${projectId}/outline-nodes`);
export const createOutlineNode = (projectId: string, payload: Partial<OutlineNode> & { title: string }) => request<OutlineNode>(`/projects/${projectId}/outline-nodes`, { method: "POST", body: JSON.stringify(payload) });
export const updateOutlineNode = (projectId: string, nodeId: string, payload: Partial<OutlineNode>) => request<OutlineNode>(`/projects/${projectId}/outline-nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteOutlineNode = (projectId: string, nodeId: string) => request<{ deleted: boolean }>(`/projects/${projectId}/outline-nodes/${nodeId}`, { method: "DELETE" });
export const proposeOutlineChange = (projectId: string, suggestion: string, preview?: Record<string, unknown>) => request<AIProposal>(`/projects/${projectId}/outline/propose-ai-change`, { method: "POST", body: JSON.stringify({ suggestion, preview }) });
export const proposeOutlineAIPlan = (projectId: string, suggestion: string) => request<AIProposal>(`/projects/${projectId}/outline/ai-plan`, { method: "POST", body: JSON.stringify({ suggestion }) });
export const applyOutlineProposal = (projectId: string, proposalId: string) => request<AIProposal>(`/projects/${projectId}/outline/proposals/${proposalId}/apply`, { method: "POST" });
export const getWorkspace = (projectId: string, nodeId: string) => request<ChapterWorkspace>(`/projects/${projectId}/chapters/${nodeId}/workspace`);
export const addSupplement = (projectId: string, nodeId: string, payload: Partial<ChapterSupplement>) => request<ChapterSupplement>(`/projects/${projectId}/chapters/${nodeId}/supplements`, { method: "POST", body: JSON.stringify(payload) });
export const updateSupplement = (projectId: string, nodeId: string, supplementId: string, payload: Partial<ChapterSupplement>) => request<ChapterSupplement>(`/projects/${projectId}/chapters/${nodeId}/supplements/${supplementId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteSupplement = (projectId: string, nodeId: string, supplementId: string) => request<{ deleted: boolean }>(`/projects/${projectId}/chapters/${nodeId}/supplements/${supplementId}`, { method: "DELETE" });
export const generateChapter = (projectId: string, nodeId: string) => request<ChapterResponse>(`/projects/${projectId}/chapters/${nodeId}/generate`, { method: "POST" });
export const getChapter = (projectId: string, nodeId: string) => request<ChapterResponse>(`/projects/${projectId}/chapters/${nodeId}`);
export const createManualVersion = (projectId: string, nodeId: string, title: string, markdown: string, select = true) => request<ChapterVersion>(`/projects/${projectId}/chapters/${nodeId}/versions`, { method: "POST", body: JSON.stringify({ title, markdown, select }) });
export const listVersions = (projectId: string, nodeId: string) => request<ChapterVersion[]>(`/projects/${projectId}/chapters/${nodeId}/versions`);
export const selectVersion = (projectId: string, nodeId: string, versionId: string) => request<ChapterVersion>(`/projects/${projectId}/chapters/${nodeId}/selected-version`, { method: "PATCH", body: JSON.stringify({ version_id: versionId }) });
export const proposeChapterEdit = (projectId: string, nodeId: string, suggestion: string, baseMarkdown?: string) => request<AIProposal>(`/projects/${projectId}/chapters/${nodeId}/propose-ai-edit`, { method: "POST", body: JSON.stringify({ suggestion, base_markdown: baseMarkdown }) });
export const applyChapterProposal = (projectId: string, nodeId: string, proposalId: string) => request<AIProposal>(`/projects/${projectId}/chapters/${nodeId}/proposals/${proposalId}/apply`, { method: "POST" });
export const generateProject = (projectId: string) => request<RunResponse>(`/projects/${projectId}/generate`, { method: "POST" });
export const mergeProject = (projectId: string) => request<RunResponse>(`/projects/${projectId}/merge`, { method: "POST" });

export async function uploadAttachment(projectId: string, nodeId: string, file: File, description: string): Promise<ChapterAttachment> {
  const form = new FormData();
  form.append("file", file);
  form.append("description", description);
  const response = await fetch(`${API_BASE}/projects/${projectId}/chapters/${nodeId}/attachments`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()) as ChapterAttachment;
}

export async function getFinalMarkdown(projectId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/artifacts/final.md`);
  if (!response.ok) throw new Error(await response.text());
  return response.text();
}
