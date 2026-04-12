import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowUp, Square, Plus, Mic, MicOff, Loader2 } from "lucide-react";
import { useSpeechToText } from "@/hooks/useVoice";

interface InputBarProps {
  onSend: (content: string) => void;
  onInterrupt: () => void;
  onNewConversation: () => void;
  isStreaming: boolean;
  isConnected: boolean;
}

export function InputBar({
  onSend,
  onInterrupt,
  onNewConversation,
  isStreaming,
  isConnected,
}: InputBarProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { isListening, isTranscribing, transcript, error: voiceError, startListening, stopListening, supported: micSupported } =
    useSpeechToText();

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [input]);

  // Sync voice transcript into input
  useEffect(() => {
    if (transcript) {
      setInput(transcript);
    }
  }, [transcript]);

  const handleSubmit = async () => {
    let text = input;
    if (isListening) {
      try {
        text = await stopListening();
      } catch {
        return;
      }
    }
    const trimmed = text.trim();
    if (!trimmed || isStreaming || !isConnected) return;
    onSend(trimmed);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const toggleMic = async () => {
    if (isListening) {
      try {
        const text = await stopListening();
        if (text.trim()) setInput(text.trim());
      } catch {
        // The hook exposes the error below the input.
      }
    } else {
      await startListening();
    }
  };

  return (
    <div className="border-t border-border bg-zinc-950/80 px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2">
          {/* New conversation button */}
          <Button
            variant="ghost"
            size="icon"
            onClick={onNewConversation}
            className="shrink-0 text-muted-foreground hover:text-foreground h-10 w-10"
            title="New conversation"
          >
            <Plus className="h-4 w-4" />
          </Button>

          {/* Input area */}
          <div
            className={cn(
              "relative flex-1 rounded-xl border bg-zinc-900/50 transition-all",
              isListening
                ? "border-red-500/50 ring-1 ring-red-500/20"
                : "border-border focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20"
            )}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isListening
                  ? "Listening..."
                  : isTranscribing
                  ? "Transcribing locally..."
                  : !isConnected
                  ? "Connecting to Hermes..."
                  : "Send a message..."
              }
              disabled={!isConnected || isTranscribing}
              rows={1}
              className="w-full resize-none bg-transparent px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
            />

            {/* Mic button inside the input */}
            {micSupported && !isStreaming && (
              <button
                onClick={toggleMic}
                disabled={isTranscribing}
                className={cn(
                  "absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 transition-colors cursor-pointer",
                  isListening
                    ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                    : isTranscribing
                    ? "text-primary"
                    : "text-muted-foreground hover:text-foreground hover:bg-zinc-800"
                )}
                title={isListening ? "Stop listening" : "Voice input"}
              >
                {isTranscribing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isListening ? (
                  <div className="relative">
                    <MicOff className="h-4 w-4" />
                    <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                  </div>
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </button>
            )}
          </div>

          {/* Send / Stop button */}
          {isStreaming ? (
            <Button
              variant="destructive"
              size="icon"
              onClick={onInterrupt}
              className="shrink-0 h-10 w-10 rounded-xl"
            >
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={handleSubmit}
              disabled={(!input.trim() && !isListening) || !isConnected || isTranscribing}
              className="shrink-0 h-10 w-10 rounded-xl"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>

        <p className={cn("mt-2 text-center text-[10px]", voiceError ? "text-amber-300" : "text-muted-foreground/60")}>
          {voiceError || "Hermes Studio wraps Hermes Agent. Responses may be inaccurate."}
        </p>
      </div>
    </div>
  );
}
