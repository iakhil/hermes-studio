import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  Monitor,
  Terminal,
  Globe,
  Eye,
  Volume2,
  Image,
  Brain,
  FileText,
  Search,
  Users,
  Clock,
  HelpCircle,
  BookOpen,
  ListChecks,
  Loader2,
  Zap,
  Home,
  FlaskConical,
  Shield,
  Sparkles,
} from "lucide-react";

interface ToolSet {
  id: string;
  name: string;
  icon: string;
  enabled: boolean;
  category: string;
}

const CATEGORY_META: Record<
  string,
  { label: string; description: string; color: string; Icon: typeof Zap }
> = {
  power: {
    label: "Computer Use",
    description: "Control your Mac — browse the web, run commands, see the screen, and speak.",
    color: "from-violet-500 to-purple-600",
    Icon: Monitor,
  },
  ai: {
    label: "AI Capabilities",
    description: "Generative AI tools — images, voice, multi-agent reasoning.",
    color: "from-amber-500 to-orange-600",
    Icon: Sparkles,
  },
  data: {
    label: "Research & Files",
    description: "Search the web, read files, and navigate the filesystem.",
    color: "from-blue-500 to-cyan-600",
    Icon: Search,
  },
  productivity: {
    label: "Productivity",
    description: "Memory, skills, task planning, scheduling, and delegation.",
    color: "from-emerald-500 to-green-600",
    Icon: ListChecks,
  },
};

const TOOL_ICONS: Record<string, typeof Terminal> = {
  browser: Globe,
  terminal: Terminal,
  code_execution: Zap,
  vision: Eye,
  tts: Volume2,
  image_gen: Image,
  moa: Brain,
  web: Search,
  file: FileText,
  session_search: Search,
  memory: Brain,
  skills: BookOpen,
  todo: ListChecks,
  delegation: Users,
  cronjob: Clock,
  clarify: HelpCircle,
  rl: FlaskConical,
  homeassistant: Home,
};

const TOOL_DESCRIPTIONS: Record<string, string> = {
  browser:
    "Full browser automation — click, type, scroll, navigate. Hermes can use any website as if it were sitting at your screen.",
  terminal:
    "Execute shell commands, manage processes, pipe output. Full control of your terminal environment.",
  code_execution:
    "Run Python, JavaScript, and other code in sandboxed environments. See output in real time.",
  vision:
    "Analyze screenshots and images. Hermes can see what's on screen and describe, OCR, or act on it.",
  tts: "Text-to-speech output. Hermes can speak responses aloud using ElevenLabs or system TTS.",
  image_gen:
    "Generate images from text prompts using DALL-E, FAL, or other providers.",
  moa: "Mixture of Agents — run multiple models in parallel and synthesize the best answer.",
  web: "Search the web with Exa, Tavily, or Google. Scrape and extract data from URLs.",
  file: "Read, write, create, delete, and search files on your filesystem.",
  session_search: "Search through past conversation sessions with full-text search.",
  memory:
    "Persistent memory across sessions — Hermes remembers what you've told it and what it's learned.",
  skills:
    "Procedural skills that Hermes creates and refines. Reusable instructions for complex tasks.",
  todo: "Task planning and tracking. Break down complex goals into actionable steps.",
  delegation:
    "Spawn sub-agents for parallel workstreams. Hermes can delegate and coordinate.",
  cronjob: "Schedule recurring tasks with natural language. Cross-platform delivery.",
  clarify: "Hermes asks clarifying questions before acting on ambiguous requests.",
  rl: "Reinforcement learning training tools for model improvement research.",
  homeassistant: "Control smart home devices through Home Assistant integration.",
};

const CATEGORY_ORDER = ["power", "ai", "data", "productivity"];

export function ToolsPage() {
  const [tools, setTools] = useState<ToolSet[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);

  useEffect(() => {
    loadTools();
  }, []);

  async function loadTools() {
    try {
      const res = await fetch("/api/v1/tools");
      if (res.ok) setTools(await res.json());
    } catch {}
    setLoading(false);
  }

  async function toggleTool(toolId: string, enabled: boolean) {
    setToggling(toolId);
    // Optimistic update
    setTools((prev) =>
      prev.map((t) => (t.id === toolId ? { ...t, enabled } : t))
    );
    try {
      const res = await fetch("/api/v1/tools/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ toolset: toolId, enabled }),
      });
      const data = await res.json();
      if (!data.success) {
        // Revert
        setTools((prev) =>
          prev.map((t) => (t.id === toolId ? { ...t, enabled: !enabled } : t))
        );
      }
    } catch {
      setTools((prev) =>
        prev.map((t) => (t.id === toolId ? { ...t, enabled: !enabled } : t))
      );
    }
    setToggling(null);
  }

  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    tools: tools.filter((t) => t.category === cat),
  })).filter((g) => g.tools.length > 0);

  const enabledCount = tools.filter((t) => t.enabled).length;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-foreground">Tools</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Control what Hermes can do. Enable computer use to let it drive your Mac.
          </p>
          <div className="flex gap-2 mt-3">
            <Badge variant="secondary">
              {enabledCount} / {tools.length} enabled
            </Badge>
          </div>
        </div>

        {/* Categories */}
        <div className="space-y-8">
          {grouped.map(({ category, tools: catTools }) => {
            const meta = CATEGORY_META[category];
            if (!meta) return null;
            const { label, description, color, Icon: CatIcon } = meta;

            return (
              <motion.div
                key={category}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                {/* Category header */}
                <div className="flex items-center gap-3 mb-4">
                  <div
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br text-white",
                      color
                    )}
                  >
                    <CatIcon className="h-4.5 w-4.5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-foreground">{label}</h2>
                    <p className="text-xs text-muted-foreground">{description}</p>
                  </div>
                </div>

                {/* Tool cards */}
                <div className="grid gap-2">
                  {catTools.map((tool) => {
                    const ToolIcon = TOOL_ICONS[tool.id] || Zap;
                    const desc = TOOL_DESCRIPTIONS[tool.id] || tool.name;
                    const isToggling = toggling === tool.id;

                    return (
                      <div
                        key={tool.id}
                        className={cn(
                          "flex items-center gap-4 rounded-xl border px-4 py-3.5 transition-all",
                          tool.enabled
                            ? "border-zinc-700/50 bg-zinc-900/50"
                            : "border-zinc-800/50 bg-zinc-950/50 opacity-60"
                        )}
                      >
                        <div
                          className={cn(
                            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
                            tool.enabled
                              ? "bg-primary/15 text-primary"
                              : "bg-zinc-800 text-zinc-500"
                          )}
                        >
                          <ToolIcon className="h-4 w-4" />
                        </div>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-foreground">
                              {tool.name}
                            </span>
                            {category === "power" && tool.enabled && (
                              <Badge
                                variant="outline"
                                className="text-[10px] px-1.5 py-0 border-primary/30 text-primary"
                              >
                                active
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                            {desc}
                          </p>
                        </div>

                        {/* Toggle switch */}
                        <button
                          onClick={() => toggleTool(tool.id, !tool.enabled)}
                          disabled={isToggling}
                          className={cn(
                            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors",
                            tool.enabled ? "bg-primary" : "bg-zinc-700",
                            isToggling && "opacity-50"
                          )}
                        >
                          <span
                            className={cn(
                              "inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
                              tool.enabled ? "translate-x-6" : "translate-x-1"
                            )}
                          />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Power user hint */}
        <div className="mt-10 rounded-xl border border-zinc-800 bg-zinc-900/30 px-5 py-4">
          <div className="flex items-start gap-3">
            <Shield className="h-5 w-5 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-foreground">About Computer Use</p>
              <p className="text-xs text-muted-foreground mt-1">
                When browser, terminal, and vision tools are enabled, Hermes can control your Mac —
                browsing websites, running commands, and seeing your screen. Tool calls require
                approval by default unless you run in <code className="text-primary">--yolo</code> mode.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
