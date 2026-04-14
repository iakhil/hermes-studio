const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8420";

function configuredBackendOrigin() {
  return (import.meta.env.VITE_HERMES_BACKEND_URL || "").replace(/\/$/, "");
}

export function apiBaseUrl() {
  const configured = configuredBackendOrigin();
  if (configured) return `${configured}/api/v1`;
  if (import.meta.env.DEV) return "/api/v1";
  return `${DEFAULT_BACKEND_ORIGIN}/api/v1`;
}

export function chatWebSocketUrl() {
  const configured = configuredBackendOrigin();
  if (!configured && import.meta.env.DEV) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/chat`;
  }

  const origin = configured || DEFAULT_BACKEND_ORIGIN;
  const url = new URL("/ws/chat", origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
