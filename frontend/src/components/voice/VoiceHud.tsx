import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, Mic } from "lucide-react";
import { cn } from "@/lib/utils";

type HudState = "registered" | "listening" | "released" | "speaking" | "unavailable";

interface VoiceHotkeyPayload {
  shortcut: string;
}

export function VoiceHud() {
  const [state, setState] = useState<HudState>("registered");

  useEffect(() => {
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
    document.body.style.overflow = "hidden";

    let cleanup = () => {};
    const onTalkBackStart = () => setState("speaking");
    const onTalkBackEnd = () => setState("registered");
    window.addEventListener("voice-talkback-start", onTalkBackStart);
    window.addEventListener("voice-talkback-end", onTalkBackEnd);

    async function bind() {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const unlistenPressed = await listen<VoiceHotkeyPayload>("voice-hotkey-pressed", () => {
          setState("listening");
        });
        const unlistenReleased = await listen<VoiceHotkeyPayload>("voice-hotkey-released", () => {
          setState("released");
        });
        const unlistenRegistered = await listen<VoiceHotkeyPayload>("voice-hotkey-registered", () => {
          setState("registered");
        });
        const unlistenUnavailable = await listen<VoiceHotkeyPayload>("voice-hotkey-unavailable", () => {
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
      window.removeEventListener("voice-talkback-start", onTalkBackStart);
      window.removeEventListener("voice-talkback-end", onTalkBackEnd);
      cleanup();
    };
  }, []);

  const listening = state === "listening";
  const released = state === "released";
  const speaking = state === "speaking";
  const unavailable = state === "unavailable";

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-transparent p-2">
      <div
        className={cn(
          "relative flex h-16 w-16 items-center justify-center rounded-lg border shadow-2xl backdrop-blur-xl transition-all duration-200",
          listening
            ? "scale-105 border-red-300/70 bg-red-950/90 shadow-red-500/30"
            : released
            ? "scale-100 border-emerald-300/60 bg-zinc-950/90 shadow-emerald-500/25"
            : speaking
            ? "scale-105 border-cyan-300/60 bg-zinc-950/90 shadow-cyan-500/25"
            : unavailable
            ? "scale-95 border-amber-300/60 bg-zinc-950/90 shadow-amber-500/20"
            : "scale-95 border-zinc-700/70 bg-zinc-950/80 shadow-black/40"
        )}
        aria-label={
          listening
            ? "Listening"
            : released
            ? "Sending voice command"
            : speaking
            ? "Speaking response"
            : unavailable
            ? "Voice hotkey unavailable"
            : "Voice hotkey ready"
        }
      >
        {listening && (
          <>
            <span className="absolute h-16 w-16 animate-ping rounded-lg bg-red-400/25" />
            <span className="absolute h-20 w-20 rounded-lg border border-red-300/30" />
          </>
        )}
        {speaking && <span className="absolute h-16 w-16 animate-pulse rounded-lg bg-cyan-400/15" />}
        {released && <span className="absolute h-16 w-16 animate-pulse rounded-lg bg-emerald-400/15" />}

        <img src="/favicon.svg" alt="" className="relative h-11 w-11 rounded-md" draggable={false} />

        <div
          className={cn(
            "absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-lg border text-[11px] shadow-lg",
            listening
              ? "border-red-200/60 bg-red-500 text-white"
              : released
              ? "border-emerald-200/60 bg-emerald-500 text-white"
              : speaking
              ? "border-cyan-200/60 bg-cyan-500 text-zinc-950"
              : unavailable
              ? "border-amber-200/60 bg-amber-500 text-zinc-950"
              : "border-zinc-700 bg-zinc-900 text-zinc-300"
          )}
        >
          {listening ? (
            <Mic className="h-3.5 w-3.5" />
          ) : released || speaking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : unavailable ? (
            <AlertTriangle className="h-3.5 w-3.5" />
          ) : (
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
          )}
        </div>
      </div>
    </div>
  );
}
