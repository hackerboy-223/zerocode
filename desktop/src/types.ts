export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  reasoning?: string;
  images?: string[];
  seq: number;
}

export interface AgentEvent {
  type: string;
  [key: string]: unknown;
}

export interface ToolActivity {
  id: string;
  name: string;
  arguments?: Record<string, unknown>;
  result?: string;
  output?: string;
  status: "running" | "success" | "error";
  seq: number;
}

export interface PermissionRequest {
  request_id: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  command?: string;
  type: "permission_request" | "sudo_confirmation_request" | "sudo_password_request";
}

export interface SessionSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed" | "cancelled";
}

export interface DiffEntry {
  id: string;
  path: string;
  diff: string;
}

export interface WorkspaceEntry {
  name: string;
  path: string;
  kind: "dir" | "file";
  size: number;
}

export interface WorkspaceFilePreview {
  path: string;
  content: string;
  lines: number;
  truncated: boolean;
}

export interface GitChangedFile {
  status: string;
  path: string;
}

export interface GitWorkspaceInfo {
  is_repo: boolean;
  branch: string;
  dirty_count: number;
  changed_files: GitChangedFile[];
}

export interface SubagentRole {
  id: string;
  description: string;
}

export interface SubagentRun {
  id: string;
  role: string;
  task: string;
  status: "running" | "done" | "error" | "stopped";
  tools: string[];
  result?: string;
  error?: string;
  durationMs?: number;
  startedAt: number;
  seq: number;
}

export interface RuntimeSettings {
  max_steps: number;
  command_timeout: number;
  max_tokens: number;
  temperature: number;
  compact_threshold: number;
  auto_compact: boolean;
  task_routing: boolean;
  fallback: boolean;
  free_only: boolean;
  diff_view: boolean;
}

export type InspectorTab = "overview" | "agents" | "files" | "changes" | "editor" | "search" | "mcp";

export interface SkillItem {
  id: string;
  label: string;
  category: string;
  summary: string;
  builtin: boolean;
}

export interface SkillsState {
  active: string[];
  available: SkillItem[];
}

export interface ProjectMemory {
  path: string;
  content: string;
}

export interface ProviderStatus {
  id: string;
  label: string;
  env_var: string;
  requires_key: boolean;
  enabled: boolean;
  available: boolean;
  source: "keyless" | "env" | "store" | "none";
  key_masked: string;
  models_count: number;
  signup_url: string;
  notes: string;
}

export interface AttachedImage {
  id: string;
  name: string;
  dataUrl: string;
}

export interface WorkspaceSearchMatch {
  path: string;
  line: number;
  snippet: string;
  score: number;
}
