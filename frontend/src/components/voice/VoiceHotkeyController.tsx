import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, MicOff, Loader2 } from "lucide-react";
import { useAgentTalkBack, useSpeechToText } from "@/hooks/useVoice";
import { useHermesChat } from "@/hooks/useHermesChat";
import { useChatStore } from "@/stores/chatStore";
import { cn } from "@/lib/utils";

interface VoiceHotkeyPayload {
  shortcut: string;
}

export function VoiceHotkeyController({ headless = false }: { headless?: boolean }) {
  const { sendMessageAndWait } = useHermesChat();
  const { isListening, isTranscribing, error, startListening, stopListening, supported } = useSpeechToText();
  const { speak, isSpeaking, error: talkBackError } = useAgentTalkBack();
  const isTranscribingRef = useRef(isTranscribing);
  const recordingStateRef = useRef<"idle" | "starting" | "listening" | "stopping">("idle");
  const releasePendingRef = useRef(false);
  const [hotkeyAvailable, setHotkeyAvailable] = useState(true);
  const [lastShortcut, setLastShortcut] = useState("Option+Command");

  useEffect(() => {
    if (isListening) recordingStateRef.current = "listening";
    else if (recordingStateRef.current === "listening") recordingStateRef.current = "idle";
  }, [isListening]);

  useEffect(() => {
    isTranscribingRef.current = isTranscribing;
  }, [isTranscribing]);

  const stopAndSend = useCallback(async () => {
    if (recordingStateRef.current === "stopping") return;
    recordingStateRef.current = "stopping";
    releasePendingRef.current = false;
    let finishedWithTalkBack = false;

    try {
      const text = (await stopListening()).trim();
      const state = useChatStore.getState();
      if (text && state.isConnected && !state.isStreaming) {
        const response = await sendMessageAndWait(text);
        window.dispatchEvent(new CustomEvent("voice-talkback-start"));
        await speak(response);
        window.dispatchEvent(new CustomEvent("voice-talkback-end"));
        finishedWithTalkBack = true;
      }
    } catch {
      // The hook exposes the current error in the status pill.
      window.dispatchEvent(new CustomEvent("voice-talkback-end"));
      finishedWithTalkBack = true;
    } finally {
      recordingStateRef.current = "idle";
      if (!finishedWithTalkBack) {
        window.dispatchEvent(new CustomEvent("voice-talkback-end"));
      }
    }
  }, [sendMessageAndWait, speak, stopListening]);

  const beginVoice = useCallback(async () => {
    if (!supported || isTranscribingRef.current || recordingStateRef.current !== "idle") return;

    releasePendingRef.current = false;
    recordingStateRef.current = "starting";
    try {
      await startListening();
      recordingStateRef.current = "listening";
      if (releasePendingRef.current) {
        await stopAndSend();
      }
    } catch {
      recordingStateRef.current = "idle";
      releasePendingRef.current = false;
      window.dispatchEvent(new CustomEvent("voice-talkback-end"));
    }
  }, [startListening, stopAndSend, supported]);

  const endVoice = useCallback(async () => {
    if (!supported) return;

    if (recordingStateRef.current === "starting") {
      releasePendingRef.current = true;
      return;
    }
    if (recordingStateRef.current === "listening") {
      await stopAndSend();
    }
  }, [stopAndSend, supported]);

  useEffect(() => {
    let cleanup = () => {};

    async function bind() {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const unlistenPressed = await listen<VoiceHotkeyPayload>("voice-hotkey-pressed", (event) => {
          setHotkeyAvailable(true);
          setLastShortcut(event.payload?.shortcut || "Option+Command");
          void beginVoice();
        });
        const unlistenReleased = await listen<VoiceHotkeyPayload>("voice-hotkey-released", (event) => {
          setHotkeyAvailable(true);
          setLastShortcut(event.payload?.shortcut || "Option+Command");
          void endVoice();
        });
        const unlistenUnavailable = await listen<VoiceHotkeyPayload>("voice-hotkey-unavailable", (event) => {
          setHotkeyAvailable(false);
          setLastShortcut(event.payload?.shortcut || "Option+Command");
        });
        cleanup = () => {
          unlistenPressed();
          unlistenReleased();
          unlistenUnavailable();
        };
      } catch {
        setHotkeyAvailable(false);
      }
    }

    void bind();
    return () => cleanup();
  }, [beginVoice, endVoice]);

  if (!supported || headless) return null;

  const status = isListening
    ? `Listening: release ${lastShortcut} to send`
    : isTranscribing
    ? "Transcribing voice command"
    : isSpeaking
    ? "Speaking response"
    : hotkeyAvailable
    ? `Hold ${lastShortcut} to talk`
    : `${lastShortcut} unavailable`;

  return (
    <div
      className={cn(
        "pointer-events-none fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs shadow-lg",
        isListening
          ? "border-red-500/40 bg-red-950/90 text-red-100"
          : error || talkBackError || !hotkeyAvailable
          ? "border-amber-500/30 bg-zinc-950/90 text-amber-200"
          : "border-zinc-800 bg-zinc-950/80 text-muted-foreground"
      )}
    >
      {isTranscribing ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : isListening ? (
        <MicOff className="h-3.5 w-3.5" />
      ) : (
        <Mic className="h-3.5 w-3.5" />
      )}
      <span>{error || talkBackError || status}</span>
    </div>
  );
}
