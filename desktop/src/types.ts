export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  reasoning?: string;
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
