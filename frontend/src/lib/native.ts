export interface MacPermissionStatus {
  platform: string;
  accessibility_trusted?: boolean | null;
  screen_recording_granted?: boolean | null;
  screen_recording_hint?: string | null;
}

export async function isNativeApp(): Promise<boolean> {
  return "__TAURI_INTERNALS__" in window;
}

export async function macPermissionStatus(): Promise<MacPermissionStatus | null> {
  if (!(await isNativeApp())) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<MacPermissionStatus>("mac_permission_status");
}

export async function requestAccessibilityPermission(): Promise<boolean> {
  if (!(await isNativeApp())) return false;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<boolean>("request_accessibility_permission");
}

export async function openMacPrivacyPane(
  pane: "accessibility" | "screen-recording" | "microphone" | "automation"
): Promise<void> {
  if (!(await isNativeApp())) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("open_macos_privacy_pane", { pane });
}

export async function requestScreenRecordingPermission(): Promise<boolean> {
  if (!(await isNativeApp())) return false;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<boolean>("request_screen_recording_permission");
}

export async function requestMicrophonePermission(): Promise<boolean> {
  if (!navigator.mediaDevices?.getUserMedia) return false;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
    return true;
  } catch {
    return false;
  }
}
