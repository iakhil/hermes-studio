import { createContext, type ReactNode, useContext } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";

type HermesChat = ReturnType<typeof useWebSocket>;

const HermesChatContext = createContext<HermesChat | null>(null);

export function HermesChatProvider({ children }: { children: ReactNode }) {
  const chat = useWebSocket();
  return <HermesChatContext.Provider value={chat}>{children}</HermesChatContext.Provider>;
}

export function useHermesChat() {
  const chat = useContext(HermesChatContext);
  if (!chat) {
    throw new Error("useHermesChat must be used inside HermesChatProvider");
  }
  return chat;
}
