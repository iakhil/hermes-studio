import { useRef, useEffect } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useHermesChat } from "@/hooks/useHermesChat";
import { MessageBubble } from "./MessageBubble";
import { InputBar } from "./InputBar";
import { Sparkles } from "lucide-react";

export function ChatContainer() {
  const { messages, isStreaming, isConnected } = useChatStore();
  const ws = useHermesChat();
  const { sendMessage, interrupt, newConversation } = ws;
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Only auto-scroll if user is near the bottom
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    if (isNearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState onSend={sendMessage} />
        ) : (
          <div className="mx-auto max-w-3xl divide-y divide-zinc-900/50">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
          </div>
        )}
      </div>

      {/* Input */}
      <InputBar
        onSend={sendMessage}
        onInterrupt={interrupt}
        onNewConversation={newConversation}
        isStreaming={isStreaming}
        isConnected={isConnected}
      />
    </div>
  );
}

function EmptyState({ onSend }: { onSend: (msg: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-purple-700/20 mb-6">
        <Sparkles className="h-8 w-8 text-primary" />
      </div>
      <h2 className="text-xl font-semibold text-foreground mb-2">Hermes Studio</h2>
      <p className="text-sm text-muted-foreground text-center max-w-md">
        The visual interface for Hermes Agent. Use native Mac apps directly, or connect Chrome only when a task explicitly needs a website.
      </p>
      <div className="mt-8 grid grid-cols-2 gap-3 max-w-sm w-full">
        {[
          "Open Notes and create a note called shopping list",
          "Open Calendar and draft an event for tomorrow at 9 AM",
          "Open WhatsApp and prepare a message to Mom",
          "Open Music and play a playlist",
        ].map((prompt) => (
          <button
            key={prompt}
            onClick={() => onSend(prompt)}
            className="rounded-xl border border-border bg-zinc-900/50 px-4 py-3 text-left text-xs text-muted-foreground hover:bg-zinc-800/50 hover:text-foreground hover:border-zinc-700 transition-all cursor-pointer"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
