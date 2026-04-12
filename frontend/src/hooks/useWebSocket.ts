import { useEffect, useRef, useCallback } from "react";
import { useChatStore } from "@/stores/chatStore";
import type { WSMessage, WSClientMessage } from "@/lib/types";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/chat`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };

    ws.onmessage = (event) => {
      const msg: WSMessage = JSON.parse(event.data);
      handleMessage(msg);
    };

    ws.onclose = () => {
      useChatStore.getState().setConnected(false);
      // Reconnect with backoff
      reconnectTimer.current = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  const handleMessage = useCallback((msg: WSMessage) => {
    const s = useChatStore.getState();

    switch (msg.type) {
      case "connected":
        useChatStore.getState().setConnected(true, msg.session_id, msg.model);
        break;
      case "delta":
        s.appendDelta(msg.text);
        break;
      case "tool_start":
        s.addToolStart(msg.id, msg.name, msg.args);
        break;
      case "tool_complete":
        s.completeToolCall(msg.id, msg.result, msg.duration_ms);
        break;
      case "thinking":
        s.appendThinking(msg.text);
        break;
      case "status":
        // Could show as a toast or status indicator
        break;
      case "error":
        s.setError(msg.message);
        break;
      case "done":
        s.finishMessage(msg.usage ?? undefined);
        break;
    }
  }, []);

  const send = useCallback((msg: WSClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const sendMessage = useCallback((content: string) => {
    const s = useChatStore.getState();
    s.addUserMessage(content);
    s.startAssistantMessage();
    send({ type: "message", content });
  }, [send]);

  const interrupt = useCallback(() => {
    send({ type: "interrupt" });
  }, [send]);

  const newConversation = useCallback(() => {
    useChatStore.getState().clearMessages();
    send({ type: "new_conversation" });
  }, [send]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { sendMessage, interrupt, newConversation, send };
}
