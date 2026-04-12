import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { ToolCall } from "@/lib/types";
import {
  ChevronDown,
  Terminal,
  FileText,
  Globe,
  Code,
  Search,
  FolderOpen,
  Loader2,
  CheckCircle2,
  XCircle,
} from "lucide-react";

const TOOL_ICONS: Record<string, typeof Terminal> = {
  bash: Terminal,
  shell: Terminal,
  execute: Terminal,
  file_read: FileText,
  file_write: FileText,
  read_file: FileText,
  write_file: FileText,
  web: Globe,
  browser: Globe,
  fetch: Globe,
  code: Code,
  python: Code,
  search: Search,
  grep: Search,
  find: Search,
  ls: FolderOpen,
  directory: FolderOpen,
};

function getToolIcon(name: string) {
  const lower = name.toLowerCase();
  for (const [key, Icon] of Object.entries(TOOL_ICONS)) {
    if (lower.includes(key)) return Icon;
  }
  return Terminal;
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return "";
  if (entries.length === 1) {
    const [, val] = entries[0];
    const str = typeof val === "string" ? val : JSON.stringify(val);
    return str.length > 80 ? str.slice(0, 77) + "..." : str;
  }
  return entries
    .map(([k, v]) => {
      const str = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}: ${str.length > 40 ? str.slice(0, 37) + "..." : str}`;
    })
    .join(", ");
}

interface ToolCallCardProps {
  tool: ToolCall & { expanded?: boolean };
  onToggle: () => void;
}

export function ToolCallCard({ tool, onToggle }: ToolCallCardProps) {
  const Icon = getToolIcon(tool.name);
  const isRunning = tool.status === "running";
  const isError = tool.status === "error";
  const expanded = (tool as any).expanded ?? false;

  return (
    <div
      className={cn(
        "rounded-lg border transition-colors my-2",
        isRunning
          ? "border-primary/30 bg-primary/5"
          : isError
          ? "border-destructive/30 bg-destructive/5"
          : "border-zinc-800 bg-zinc-900/50"
      )}
    >
      {/* Header */}
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left cursor-pointer"
      >
        <div
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
            isRunning ? "bg-primary/20 text-primary" : "bg-zinc-800 text-zinc-400"
          )}
        >
          {isRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Icon className="h-3.5 w-3.5" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-foreground">{tool.name}</span>
            {tool.duration_ms != null && (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                {tool.duration_ms < 1000
                  ? `${tool.duration_ms}ms`
                  : `${(tool.duration_ms / 1000).toFixed(1)}s`}
              </Badge>
            )}
            {tool.status === "complete" && (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            )}
            {isError && <XCircle className="h-3.5 w-3.5 text-destructive" />}
          </div>
          {!expanded && (
            <p className="text-xs text-muted-foreground truncate mt-0.5">
              {formatArgs(tool.args)}
            </p>
          )}
        </div>

        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>

      {/* Expanded content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-zinc-800 px-3 py-3 space-y-3">
              {/* Args */}
              {Object.keys(tool.args).length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                    Arguments
                  </p>
                  <pre className="text-xs bg-zinc-950 rounded-md p-2 overflow-x-auto text-zinc-300">
                    {JSON.stringify(tool.args, null, 2)}
                  </pre>
                </div>
              )}

              {/* Result */}
              {tool.result && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                    Result
                  </p>
                  <pre className="text-xs bg-zinc-950 rounded-md p-2 overflow-x-auto text-zinc-300 max-h-60 overflow-y-auto">
                    {tool.result}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
