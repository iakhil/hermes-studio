import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { ToolCallCard } from "./ToolCallCard";
import { useChatStore } from "@/stores/chatStore";
import { useTextToSpeech } from "@/hooks/useVoice";
import { User, Bot, Brain, Volume2, VolumeX, Copy, Check } from "lucide-react";
import { useState } from "react";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const toggleToolExpanded = useChatStore((s) => s.toggleToolExpanded);
  const { speak, stop, isSpeaking, supported: ttsSupported } = useTextToSpeech();
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";
  const isDone = message.status === "done";

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "group flex gap-3 px-4 py-4",
        isUser ? "bg-transparent" : "bg-zinc-900/30"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          isUser
            ? "bg-zinc-800 text-zinc-300"
            : "bg-gradient-to-br from-violet-500 to-purple-700 text-white"
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            {isUser ? "You" : "Hermes"}
          </span>
          {message.status === "streaming" && (
            <span className="flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-[10px] text-primary">streaming</span>
            </span>
          )}

          {/* Action buttons — appear on hover for assistant messages */}
          {!isUser && isDone && message.content && (
            <div className="flex items-center gap-0.5 ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
              {ttsSupported && (
                <button
                  onClick={() => (isSpeaking ? stop() : speak(message.content))}
                  className="rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-zinc-800 transition-colors cursor-pointer"
                  title={isSpeaking ? "Stop speaking" : "Read aloud"}
                >
                  {isSpeaking ? (
                    <VolumeX className="h-3.5 w-3.5" />
                  ) : (
                    <Volume2 className="h-3.5 w-3.5" />
                  )}
                </button>
              )}
              <button
                onClick={handleCopy}
                className="rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-zinc-800 transition-colors cursor-pointer"
                title="Copy"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          )}
        </div>

        {/* Thinking block */}
        {message.thinking && (
          <details className="group/think mb-2">
            <summary className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
              <Brain className="h-3 w-3" />
              <span>Thinking...</span>
            </summary>
            <div className="mt-2 pl-4 border-l-2 border-zinc-800 text-xs text-zinc-500 whitespace-pre-wrap">
              {message.thinking}
            </div>
          </details>
        )}

        {/* Tool calls */}
        {message.toolCalls.length > 0 && (
          <div className="space-y-1">
            {message.toolCalls.map((tool) => (
              <ToolCallCard
                key={tool.id}
                tool={tool}
                onToggle={() => toggleToolExpanded(message.id, tool.id)}
              />
            ))}
          </div>
        )}

        {/* Main content */}
        {message.content && (
          <div className="max-w-none">
            {isUser ? (
              <p className="text-sm text-foreground whitespace-pre-wrap">{message.content}</p>
            ) : (
              <MarkdownRenderer content={message.content} />
            )}
          </div>
        )}

        {/* Streaming cursor */}
        {message.status === "streaming" && !message.content && message.toolCalls.length === 0 && (
          <div className="flex items-center gap-1 py-2">
            <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce [animation-delay:0ms]" />
            <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce [animation-delay:150ms]" />
            <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce [animation-delay:300ms]" />
          </div>
        )}

        {/* Error state */}
        {message.status === "error" && (
          <div className="mt-2 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-xs text-destructive">
            {message.content || "An error occurred while generating the response."}
          </div>
        )}

        {/* Usage info */}
        {message.usage && (
          <div className="mt-2 text-[10px] text-muted-foreground">
            {message.usage.total_tokens.toLocaleString()} tokens
          </div>
        )}
      </div>
    </motion.div>
  );
}
