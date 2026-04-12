import { useChatStore } from "@/stores/chatStore";
import { Badge } from "@/components/ui/badge";
import { Layers, Wifi, WifiOff } from "lucide-react";
import { useLocation } from "react-router-dom";

const TITLES: Record<string, string> = {
  "/": "Chat",
  "/setup": "Setup",
  "/computer-use": "Computer Use",
  "/connections": "Connections",
  "/tools": "Tools",
};

export function Header() {
  const { isConnected, currentModel } = useChatStore();
  const location = useLocation();
  const title = TITLES[location.pathname] || "Hermes Studio";

  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-6">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-medium text-foreground">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        {/* Model indicator */}
        <Badge variant="secondary" className="gap-1.5 font-mono text-xs">
          <Layers className="h-3 w-3" />
          {currentModel}
        </Badge>

        {/* Connection status */}
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <>
              <Wifi className="h-3.5 w-3.5 text-emerald-400" />
              <span className="text-xs text-emerald-400">Connected</span>
            </>
          ) : (
            <>
              <WifiOff className="h-3.5 w-3.5 text-zinc-500" />
              <span className="text-xs text-zinc-500">Disconnected</span>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
