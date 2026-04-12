import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowUp, Square, Plus, Mic, MicOff } from "lucide-react";
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
  const { isListening, transcript, startListening, stopListening, supported: micSupported } =
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

  const handleSubmit = () => {
    if (isListening) stopListening();
    const trimmed = input.trim();
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

  const toggleMic = () => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
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
                  : !isConnected
                  ? "Connecting to Hermes..."
                  : "Send a message..."
              }
              disabled={!isConnected}
              rows={1}
              className="w-full resize-none bg-transparent px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
            />

            {/* Mic button inside the input */}
            {micSupported && !isStreaming && (
              <button
                onClick={toggleMic}
                className={cn(
                  "absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 transition-colors cursor-pointer",
                  isListening
                    ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                    : "text-muted-foreground hover:text-foreground hover:bg-zinc-800"
                )}
                title={isListening ? "Stop listening" : "Voice input"}
              >
                {isListening ? (
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
              disabled={!input.trim() || !isConnected}
              className="shrink-0 h-10 w-10 rounded-xl"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>

        <p className="mt-2 text-center text-[10px] text-muted-foreground/60">
          Hermes Studio wraps Hermes Agent. Responses may be inaccurate.
        </p>
      </div>
    </div>
  );
}
