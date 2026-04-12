import { create } from "zustand";
import type { ChatMessage, ToolCall, TokenUsage } from "@/lib/types";

interface ChatState {
  messages: ChatMessage[];
  isConnected: boolean;
  isStreaming: boolean;
  sessionId: string | null;
  currentModel: string;
  error: string | null;

  // Actions
  addUserMessage: (content: string) => string;
  startAssistantMessage: () => string;
  appendDelta: (text: string) => void;
  addToolStart: (id: string, name: string, args: Record<string, unknown>) => void;
  completeToolCall: (id: string, result: string, duration_ms: number) => void;
  appendThinking: (text: string) => void;
  finishMessage: (usage?: TokenUsage) => void;
  setError: (error: string) => void;
  setConnected: (connected: boolean, sessionId?: string, model?: string) => void;
  clearMessages: () => void;
  toggleToolExpanded: (messageId: string, toolId: string) => void;
}

let messageCounter = 0;

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isConnected: false,
  isStreaming: false,
  sessionId: null,
  currentModel: "not configured",
  error: null,

  addUserMessage: (content: string) => {
    const id = `msg-${++messageCounter}`;
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id,
          role: "user",
          content,
          toolCalls: [],
          thinking: "",
          status: "done",
          timestamp: Date.now(),
        },
      ],
      error: null,
    }));
    return id;
  },

  startAssistantMessage: () => {
    const id = `msg-${++messageCounter}`;
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id,
          role: "assistant",
          content: "",
          toolCalls: [],
          thinking: "",
          status: "streaming",
          timestamp: Date.now(),
        },
      ],
      isStreaming: true,
    }));
    return id;
  },

  appendDelta: (text: string) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: last.content + text, status: "streaming" };
      }
      return { messages: msgs };
    });
  },

  addToolStart: (id: string, name: string, args: Record<string, unknown>) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        const toolCall: ToolCall = { id, name, args, status: "running" };
        msgs[msgs.length - 1] = {
          ...last,
          toolCalls: [...last.toolCalls, toolCall],
          status: "tool_calling",
        };
      }
      return { messages: msgs };
    });
  },

  completeToolCall: (id: string, result: string, duration_ms: number) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        const toolCalls = last.toolCalls.map((tc) =>
          tc.id === id ? { ...tc, result, status: "complete" as const, duration_ms } : tc
        );
        msgs[msgs.length - 1] = { ...last, toolCalls, status: "streaming" };
      }
      return { messages: msgs };
    });
  },

  appendThinking: (text: string) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, thinking: last.thinking + text };
      }
      return { messages: msgs };
    });
  },

  finishMessage: (usage?: TokenUsage) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, status: "done", usage };
      }
      return { messages: msgs, isStreaming: false };
    });
  },

  setError: (error: string) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.status !== "done") {
        msgs[msgs.length - 1] = {
          ...last,
          content: last.content || error,
          status: "error",
        };
      }
      return { messages: msgs, isStreaming: false, error };
    });
  },

  setConnected: (connected, sessionId, model) => {
    set({
      isConnected: connected,
      ...(sessionId && { sessionId }),
      ...(model && { currentModel: model }),
    });
  },

  clearMessages: () => set({ messages: [], error: null }),

  toggleToolExpanded: (messageId: string, toolId: string) => {
    set((s) => {
      const msgs = s.messages.map((m) => {
        if (m.id !== messageId) return m;
        return {
          ...m,
          toolCalls: m.toolCalls.map((tc) =>
            tc.id === toolId ? { ...tc, expanded: !tc.expanded } : tc
          ),
        };
      });
      return { messages: msgs };
    });
  },
}));
