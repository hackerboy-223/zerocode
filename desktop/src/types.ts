export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
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
