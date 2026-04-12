import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  MessageSquare,
  Settings,
  Wrench,
  Brain,
  Layers,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  Monitor,
  Smartphone,
} from "lucide-react";
import { useState } from "react";

const navItems = [
  { to: "/", icon: MessageSquare, label: "Chat" },
  { to: "/setup", icon: Settings, label: "Setup" },
  { to: "/computer-use", icon: Monitor, label: "Computer Use" },
  { to: "/connections", icon: Smartphone, label: "Connections" },
  { to: "/tools", icon: Wrench, label: "Tools" },
  { to: "/models", icon: Layers, label: "Models", disabled: true },
  { to: "/skills", icon: Sparkles, label: "Skills", disabled: true },
  { to: "/memory", icon: Brain, label: "Memory", disabled: true },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-border bg-zinc-950/50 transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-3 border-b border-border px-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-purple-700">
          <Sparkles className="h-4 w-4 text-white" />
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold tracking-tight">Hermes Studio</span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 p-3">
        {navItems.map(({ to, icon: Icon, label, disabled }) => (
          <NavLink
            key={to}
            to={disabled ? "#" : to}
            onClick={disabled ? (e) => e.preventDefault() : undefined}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                isActive && !disabled
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
                disabled && "opacity-40 cursor-not-allowed"
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && (
              <span className="truncate">
                {label}
                {disabled && " (soon)"}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex h-10 items-center justify-center border-t border-border text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>
    </aside>
  );
}
