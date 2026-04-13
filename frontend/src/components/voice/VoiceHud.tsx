import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Mic } from "lucide-react";
import { cn } from "@/lib/utils";

type HudState = "registered" | "listening" | "released" | "speaking" | "unavailable";

interface VoiceHotkeyPayload {
  shortcut: string;
}

export function VoiceHud() {
  const [state, setState] = useState<HudState>("registered");
  const [shortcut, setShortcut] = useState("Option+Command");

  useEffect(() => {
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
    document.body.style.overflow = "hidden";

    let cleanup = () => {};
    let hideTimer: number | null = null;
    const hideSoon = (delay = 1200) => {
      if (hideTimer) window.clearTimeout(hideTimer);
      hideTimer = window.setTimeout(async () => {
        try {
          const { getCurrentWindow } = await import("@tauri-apps/api/window");
          await getCurrentWindow().hide();
        } catch {
          // The HUD can still be used in a browser preview without Tauri window APIs.
        }
      }, delay);
    };
    const showUntilNextState = () => {
      if (hideTimer) window.clearTimeout(hideTimer);
      hideTimer = null;
    };
    const onTalkBackStart = () => {
      showUntilNextState();
      setState("speaking");
    };
    const onTalkBackEnd = () => {
      setState("registered");
      hideSoon(900);
    };
    window.addEventListener("voice-talkback-start", onTalkBackStart);
    window.addEventListener("voice-talkback-end", onTalkBackEnd);
    hideSoon(1400);

    async function bind() {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const unlistenPressed = await listen<VoiceHotkeyPayload>("voice-hotkey-pressed", (event) => {
          showUntilNextState();
          setShortcut(event.payload?.shortcut || "Option+Command");
          setState("listening");
        });
        const unlistenReleased = await listen<VoiceHotkeyPayload>("voice-hotkey-released", (event) => {
          showUntilNextState();
          setShortcut(event.payload?.shortcut || "Option+Command");
          setState("released");
        });
        const unlistenRegistered = await listen<VoiceHotkeyPayload>("voice-hotkey-registered", (event) => {
          setShortcut(event.payload?.shortcut || "Option+Command");
          setState("registered");
          hideSoon(1400);
        });
        const unlistenUnavailable = await listen<VoiceHotkeyPayload>("voice-hotkey-unavailable", (event) => {
          setShortcut(event.payload?.shortcut || "Option+Command");
          setState("unavailable");
        });
        cleanup = () => {
          unlistenPressed();
          unlistenReleased();
          unlistenRegistered();
          unlistenUnavailable();
        };
      } catch {
        setState("unavailable");
      }
    }

    void bind();
    return () => {
      if (hideTimer) window.clearTimeout(hideTimer);
      window.removeEventListener("voice-talkback-start", onTalkBackStart);
      window.removeEventListener("voice-talkback-end", onTalkBackEnd);
      cleanup();
    };
  }, []);

  const listening = state === "listening";
  const released = state === "released";
  const speaking = state === "speaking";

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-transparent p-3">
      <div
        className={cn(
          "flex w-full items-center gap-3 rounded-lg border px-4 py-3 shadow-2xl backdrop-blur-xl transition-all",
          listening
            ? "scale-100 border-red-400/40 bg-zinc-950/90 text-red-100"
            : released
            ? "scale-95 border-emerald-400/40 bg-zinc-950/90 text-emerald-100"
            : speaking
            ? "scale-100 border-primary/40 bg-zinc-950/90 text-zinc-100"
            : "scale-95 border-zinc-700/70 bg-zinc-950/80 text-zinc-200"
        )}
      >
        <div
          className={cn(
            "relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
            listening ? "bg-red-500/20 text-red-200" : released ? "bg-emerald-500/20 text-emerald-200" : speaking ? "bg-primary/20 text-primary" : "bg-zinc-800 text-zinc-300"
          )}
        >
          {listening && <span className="absolute h-10 w-10 animate-ping rounded-lg bg-red-400/20" />}
          {listening ? <Mic className="relative h-5 w-5" /> : released || speaking ? <Loader2 className="h-5 w-5 animate-spin" /> : <CheckCircle2 className="h-5 w-5" />}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold">
            {listening ? "Listening" : released ? "Sending voice command" : speaking ? "Speaking response" : state === "unavailable" ? "Hotkey unavailable" : "Voice hotkey registered"}
          </div>
          <div className="mt-0.5 truncate text-xs text-zinc-400">
            {listening ? `Release ${shortcut} to send` : released ? "Transcribing locally" : speaking ? "Talk-back is playing" : `Hold ${shortcut} to talk`}
          </div>
        </div>
      </div>
    </div>
  );
}
