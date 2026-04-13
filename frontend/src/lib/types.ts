// WebSocket message types (backend -> frontend)
export type WSMessage =
  | { type: "connected"; session_id: string; model: string }
  | { type: "delta"; text: string }
  | { type: "tool_start"; id: string; name: string; args: Record<string, unknown> }
  | { type: "tool_complete"; id: string; name: string; result: string; duration_ms: number }
  | { type: "thinking"; text: string }
  | { type: "status"; message: string }
  | { type: "error"; message: string }
  | { type: "done"; usage?: TokenUsage }
  | { type: "clarify"; question: string; choices: string[] }
  | { type: "approval"; id: string; command: string; description: string };

// WebSocket message types (frontend -> backend)
export type WSClientMessage =
  | { type: "message"; content: string }
  | { type: "clarify_response"; value: string }
  | { type: "approval_response"; id: string; approved: boolean }
  | { type: "interrupt" }
  | { type: "new_conversation" };

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "running" | "complete" | "error";
  duration_ms?: number;
  expanded?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  thinking: string;
  status: "streaming" | "tool_calling" | "done" | "error";
  usage?: TokenUsage;
  timestamp: number;
}

export interface Provider {
  id: string;
  name: string;
  description: string;
  requires_key: boolean;
  configured: boolean;
  icon: string;
}

export interface Model {
  id: string;
  name: string;
  provider: string;
  context_length?: number;
}

export interface HealthStatus {
  hermes_installed: boolean;
  hermes_version?: string;
  configured: boolean;
  current_model?: string;
  current_provider?: string;
}

export interface SetupConfig {
  provider: string;
  api_key?: string;
  model: string;
  base_url?: string;
}

export interface DoctorCheck {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
  action?: string | null;
}

export interface DoctorStatus {
  installed: boolean;
  version?: string | null;
  configured: boolean;
  current_model?: string | null;
  current_provider?: string | null;
  checks: DoctorCheck[];
  doctor: {
    success: boolean;
    stdout: string;
    stderr: string;
    duration_ms: number;
  };
}

export interface ToolPreset {
  id: string;
  name: string;
  description: string;
  required: string[];
  recommended: string[];
}

export interface GatewayStatus {
  running: boolean;
  pid?: number | null;
  logs: string[];
}

export interface TelegramStatus {
  configured: boolean;
  allowed_users: string;
  home_channel: string;
}

export interface VoiceEngineStatus {
  id: string;
  name: string;
  available: boolean;
  detail: string;
  install_hint: string;
}

export interface VoiceStatus {
  configured: boolean;
  active_engine?: string | null;
  engines: VoiceEngineStatus[];
  recording: {
    format: string;
    privacy: string;
  };
}

export interface VoiceTranscription {
  text: string;
  engine: string;
  duration_ms: number;
}

export interface TtsEngineStatus {
  id: string;
  name: string;
  available: boolean;
  configured: boolean;
  detail: string;
  install_hint: string;
}

export interface TtsStatus {
  configured: boolean;
  active_engine?: string | null;
  engines: TtsEngineStatus[];
  elevenlabs_configured: boolean;
  privacy: string;
}

export interface ComputerUseStatus {
  browser_cdp_url: string;
  chrome_connected: boolean;
  profile_dir: string;
  mode: string;
  detail: string;
}
