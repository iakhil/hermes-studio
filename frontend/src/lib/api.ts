const BASE = "/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API error ${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  health: () => request<import("./types").HealthStatus>("/health"),
  doctor: () => request<import("./types").DoctorStatus>("/doctor"),

  // Setup
  checkInstall: () => request<{ installed: boolean; version?: string }>("/setup/check-install"),
  getProviders: () => request<import("./types").Provider[]>("/setup/providers"),
  configureProvider: (data: { provider: string; api_key?: string; base_url?: string }) =>
    request<{ success: boolean }>("/setup/configure-provider", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getModels: (provider: string) =>
    request<import("./types").Model[]>(`/setup/models?provider=${provider}`),
  selectModel: (model_id: string, provider?: string) =>
    request<{ success: boolean }>("/setup/select-model", {
      method: "POST",
      body: JSON.stringify({ model_id, provider }),
    }),
  testConnection: () =>
    request<{ success: boolean; response?: string; latency_ms?: number; error?: string }>(
      "/setup/test-connection",
      { method: "POST" }
    ),

  // Tools and presets
  getTools: () => request<Array<{ id: string; name: string; icon: string; enabled: boolean; category: string }>>("/tools"),
  applyPreset: (presetId: string, platform = "cli") =>
    request<{ success: boolean; error?: string }>(`/tools/presets/${presetId}/apply?platform=${platform}`, {
      method: "POST",
    }),

  // Gateway
  gatewayStatus: () => request<import("./types").GatewayStatus>("/gateway/status"),
  startGateway: () =>
    request<import("./types").GatewayStatus>("/gateway/start", { method: "POST" }),
  stopGateway: () =>
    request<import("./types").GatewayStatus>("/gateway/stop", { method: "POST" }),
  telegramStatus: () => request<import("./types").TelegramStatus>("/gateway/telegram"),
  saveTelegram: (data: { bot_token: string; allowed_users: string; home_channel?: string }) =>
    request<{ success: boolean }>("/gateway/telegram", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Local voice
  voiceStatus: () => request<import("./types").VoiceStatus>("/voice/status"),
  transcribeVoice: async (audio: Blob) => {
    const res = await fetch(`${BASE}/voice/transcribe`, {
      method: "POST",
      headers: { "Content-Type": audio.type || "audio/webm" },
      body: audio,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Voice transcription failed ${res.status}: ${body}`);
    }
    return res.json() as Promise<import("./types").VoiceTranscription>;
  },

  // Computer use
  computerUseStatus: () => request<import("./types").ComputerUseStatus>("/computer-use/status"),
  connectComputerUseBrowser: () =>
    request<{ success: boolean; chrome_connected: boolean; browser_cdp_url: string; profile_dir: string; error?: string | null }>(
      "/computer-use/connect-browser",
      { method: "POST" }
    ),
  disconnectComputerUseBrowser: () =>
    request<{ success: boolean; chrome_connected: boolean }>("/computer-use/disconnect-browser", {
      method: "POST",
    }),
};
