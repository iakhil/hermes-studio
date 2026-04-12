import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GatewayStatus, TelegramStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  MessageCircle,
  Play,
  RefreshCw,
  Smartphone,
  Square,
  TriangleAlert,
} from "lucide-react";

export function ConnectionsPage() {
  const [telegram, setTelegram] = useState<TelegramStatus | null>(null);
  const [gateway, setGateway] = useState<GatewayStatus | null>(null);
  const [botToken, setBotToken] = useState("");
  const [allowedUsers, setAllowedUsers] = useState("");
  const [homeChannel, setHomeChannel] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyGateway, setBusyGateway] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void loadGatewayOnly();
    }, 3000);
    return () => window.clearInterval(timer);
  }, []);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [telegramStatus, gatewayStatus] = await Promise.all([
        api.telegramStatus(),
        api.gatewayStatus(),
      ]);
      setTelegram(telegramStatus);
      setGateway(gatewayStatus);
      setAllowedUsers(telegramStatus.allowed_users || "");
      setHomeChannel(telegramStatus.home_channel || "");
    } catch (e: any) {
      setError(e.message || "Could not load connection status.");
    }
    setLoading(false);
  }

  async function loadGatewayOnly() {
    try {
      setGateway(await api.gatewayStatus());
    } catch {
      // keep current status visible
    }
  }

  async function saveTelegram() {
    setSaving(true);
    setError("");
    try {
      await api.saveTelegram({
        bot_token: botToken,
        allowed_users: allowedUsers,
        home_channel: homeChannel || undefined,
      });
      setBotToken("");
      await load();
    } catch (e: any) {
      setError(e.message || "Could not save Telegram settings.");
    }
    setSaving(false);
  }

  async function startGateway() {
    setBusyGateway(true);
    setError("");
    try {
      setGateway(await api.startGateway());
    } catch (e: any) {
      setError(e.message || "Could not start gateway.");
    }
    setBusyGateway(false);
  }

  async function stopGateway() {
    setBusyGateway(true);
    setError("");
    try {
      setGateway(await api.stopGateway());
    } catch (e: any) {
      setError(e.message || "Could not stop gateway.");
    }
    setBusyGateway(false);
  }

  const configured = Boolean(telegram?.configured);
  const running = Boolean(gateway?.running);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <Smartphone className="h-5 w-5 text-primary" />
              <Badge variant={running ? "success" : configured ? "secondary" : "outline"}>
                {running ? "gateway running" : configured ? "configured" : "not connected"}
              </Badge>
            </div>
            <h1 className="text-2xl font-bold text-foreground">Phone Connections</h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              Connect Hermes to Telegram first. Once the gateway is running, you can message your agent from your phone and send voice memos.
            </p>
          </div>
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
            <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <div className="mb-5 flex items-start justify-between gap-4">
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <MessageCircle className="h-5 w-5 text-primary" />
                    <h2 className="text-base font-semibold text-foreground">Telegram</h2>
                    {configured && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Create a bot with BotFather, paste the token, and restrict access to your numeric Telegram user ID.
                  </p>
                </div>
                <a
                  href="https://t.me/BotFather"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
                >
                  BotFather
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    Bot token
                  </label>
                  <Input
                    type="password"
                    value={botToken}
                    onChange={(e) => setBotToken(e.target.value)}
                    placeholder={configured ? "Token saved. Paste a new token to replace it." : "123456789:ABC..."}
                    className="font-mono"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    Allowed Telegram user IDs
                  </label>
                  <Input
                    value={allowedUsers}
                    onChange={(e) => setAllowedUsers(e.target.value)}
                    placeholder="123456789,987654321"
                    className="font-mono"
                  />
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Message @userinfobot in Telegram to get your numeric user ID.
                  </p>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    Home channel
                  </label>
                  <Input
                    value={homeChannel}
                    onChange={(e) => setHomeChannel(e.target.value)}
                    placeholder="Optional. Defaults to your DM after /sethome."
                    className="font-mono"
                  />
                </div>

                <Button
                  onClick={saveTelegram}
                  disabled={saving || !allowedUsers.trim() || (!configured && !botToken.trim())}
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Save Telegram
                </Button>
              </div>
            </section>

            <aside className="space-y-4">
              <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
                <h2 className="mb-3 text-sm font-semibold text-foreground">Gateway</h2>
                <div className="mb-4 rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2 text-xs text-muted-foreground">
                  {running ? `Running${gateway?.pid ? ` as pid ${gateway.pid}` : ""}` : "Stopped"}
                </div>
                <div className="flex gap-2">
                  <Button className="flex-1" onClick={startGateway} disabled={busyGateway || running || !configured}>
                    {busyGateway && !running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    Start
                  </Button>
                  <Button className="flex-1" variant="outline" onClick={stopGateway} disabled={busyGateway || !running}>
                    <Square className="h-4 w-4" />
                    Stop
                  </Button>
                </div>
                {!configured && (
                  <div className="mt-4 flex gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-200">
                    <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    Save Telegram settings before starting the gateway.
                  </div>
                )}
              </section>

              <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
                <h2 className="mb-3 text-sm font-semibold text-foreground">Gateway Logs</h2>
                <div className="h-64 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 font-mono text-[11px] text-zinc-400">
                  {gateway?.logs.length ? (
                    gateway.logs.map((line, i) => <div key={`${line}-${i}`}>{line}</div>)
                  ) : (
                    <div className="text-muted-foreground">No gateway output yet.</div>
                  )}
                </div>
              </section>

              <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
                <h2 className="mb-2 text-sm font-semibold text-foreground">WhatsApp Next</h2>
                <p className="text-xs text-muted-foreground">
                  WhatsApp pairing needs a QR-code bridge and dedicated-number guidance. Telegram is the safer first mobile path; WhatsApp should follow once gateway logs and process control are stable.
                </p>
              </section>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}
