import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import {
  macPermissionStatus,
  openMacPrivacyPane,
  requestAccessibilityPermission,
  requestMicrophonePermission,
  requestScreenRecordingPermission,
  type MacPermissionStatus,
} from "@/lib/native";
import type { ComputerUseStatus, DoctorStatus, VoiceStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  Circle,
  Loader2,
  Mic,
  Monitor,
  RefreshCw,
  Shield,
  Terminal,
  Volume2,
  XCircle,
} from "lucide-react";

interface ToolSet {
  id: string;
  name: string;
  icon: string;
  enabled: boolean;
  category: string;
}

const REQUIRED = ["browser", "terminal", "vision", "file"];
const RECOMMENDED = ["memory", "tts", "cronjob", "web"];

const MAC_PERMISSIONS = [
  {
    name: "Accessibility",
    detail: "Allows trusted automation to click, type, and control apps when Hermes runs local computer tasks.",
  },
  {
    name: "Screen Recording",
    detail: "Lets vision tools inspect what is visible on your display.",
  },
  {
    name: "Microphone",
    detail: "Needed for voice commands in the browser and voice messages through phone connections.",
  },
  {
    name: "Automation",
    detail: "macOS may ask the first time Hermes controls apps like Safari, Chrome, Calendar, Music, or FaceTime.",
  },
];

export function ComputerUsePage() {
  const [tools, setTools] = useState<ToolSet[]>([]);
  const [doctor, setDoctor] = useState<DoctorStatus | null>(null);
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [computerUse, setComputerUse] = useState<ComputerUseStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [connectingBrowser, setConnectingBrowser] = useState(false);
  const [error, setError] = useState("");
  const [nativeStatus, setNativeStatus] = useState<MacPermissionStatus | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [toolData, doctorData, voiceData, computerUseData] = await Promise.all([
        api.getTools(),
        api.doctor(),
        api.voiceStatus(),
        api.computerUseStatus(),
      ]);
      setTools(toolData);
      setDoctor(doctorData);
      setVoice(voiceData);
      setComputerUse(computerUseData);
      setNativeStatus(await macPermissionStatus());
    } catch (e: any) {
      setError(e.message || "Could not load Hermes status.");
    }
    setLoading(false);
  }

  async function enablePreset() {
    setApplying(true);
    setError("");
    try {
      const res = await api.applyPreset("computer_use");
      if (!res.success) setError(res.error || "Preset did not apply cleanly.");
      await load();
    } catch (e: any) {
      setError(e.message || "Preset failed.");
    }
    setApplying(false);
  }

  async function connectBrowser() {
    setConnectingBrowser(true);
    setError("");
    try {
      const res = await api.connectComputerUseBrowser();
      if (!res.success) setError(res.error || "Chrome did not expose its automation endpoint.");
      await load();
    } catch (e: any) {
      setError(e.message || "Could not connect Chrome.");
    }
    setConnectingBrowser(false);
  }

  const enabled = useMemo(() => new Set(tools.filter((t) => t.enabled).map((t) => t.id)), [tools]);
  const requiredReady = REQUIRED.every((id) => enabled.has(id));
  const recommendedReady = RECOMMENDED.filter((id) => enabled.has(id)).length;
  const ready = Boolean(doctor?.installed && doctor.configured && requiredReady);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <Monitor className="h-5 w-5 text-primary" />
              <Badge variant={ready ? "success" : "secondary"}>
                {ready ? "ready" : "setup needed"}
              </Badge>
            </div>
            <h1 className="text-2xl font-bold text-foreground">Computer Use</h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              Give Hermes the tools it needs to operate native Mac apps with local automation, screen understanding, files, memory, voice, and scheduled tasks.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={load} disabled={loading}>
              <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
              Refresh
            </Button>
            <Button onClick={enablePreset} disabled={applying || loading}>
              {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Terminal className="h-4 w-4" />}
              Enable Preset
            </Button>
          </div>
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
          <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
            <div className="space-y-6">
              <section>
                <h2 className="mb-3 text-sm font-semibold text-foreground">Required Tools</h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {REQUIRED.map((id) => (
                    <ToolRow key={id} tool={tools.find((t) => t.id === id)} enabled={enabled.has(id)} required />
                  ))}
                </div>
              </section>

              <section>
                <h2 className="mb-3 text-sm font-semibold text-foreground">Recommended Add-Ons</h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {RECOMMENDED.map((id) => (
                    <ToolRow key={id} tool={tools.find((t) => t.id === id)} enabled={enabled.has(id)} />
                  ))}
                </div>
              </section>

              <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 px-5 py-4">
                <div className="mb-4 flex items-start gap-3">
                  <Shield className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                  <div>
                    <h2 className="text-sm font-semibold text-foreground">macOS Permission Checklist</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      macOS asks for these permissions at the app or terminal level. Hermes Studio cannot grant them silently, but it can make the missing step obvious.
                    </p>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <PermissionCard
                    name="Accessibility"
                    detail={MAC_PERMISSIONS[0].detail}
                    ok={nativeStatus?.accessibility_trusted ?? null}
                    onOpen={async () => {
                      await requestAccessibilityPermission();
                      setNativeStatus(await macPermissionStatus());
                    }}
                  />
                  <PermissionCard
                    name="Screen Recording"
                    detail={MAC_PERMISSIONS[1].detail}
                    ok={nativeStatus?.screen_recording_granted ?? null}
                    onOpen={async () => {
                      await requestScreenRecordingPermission();
                      await openMacPrivacyPane("screen-recording");
                      setNativeStatus(await macPermissionStatus());
                    }}
                  />
                  <PermissionCard
                    name="Microphone"
                    detail={MAC_PERMISSIONS[2].detail}
                    ok={null}
                    onOpen={async () => {
                      await requestMicrophonePermission();
                      await openMacPrivacyPane("microphone");
                    }}
                  />
                  <PermissionCard
                    name="Automation"
                    detail={MAC_PERMISSIONS[3].detail}
                    ok={null}
                    onOpen={() => openMacPrivacyPane("automation")}
                  />
                </div>
                {!nativeStatus && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    Native permission checks appear when Hermes Studio is running as the macOS app.
                  </p>
                )}
              </section>
            </div>

            <aside className="space-y-4">
              <StatusPanel doctor={doctor} ready={ready} requiredReady={requiredReady} recommendedReady={recommendedReady} voiceReady={Boolean(voice?.configured)} browserReady={Boolean(computerUse?.chrome_connected)} />
              <NativeAutomationPanel />
              <BrowserSessionPanel status={computerUse} loading={connectingBrowser} onConnect={connectBrowser} />
              <VoicePanel voice={voice} />
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Volume2 className="h-4 w-4 text-primary" />
                  Try It
                </div>
                <div className="space-y-2 text-xs text-muted-foreground">
                  <p>After the preset is ready, use chat or voice:</p>
                  <Prompt>Open Notes and create a note called shopping list.</Prompt>
                  <Prompt>Open Calendar and draft an event for tomorrow at 9 AM.</Prompt>
                  <Prompt>Open WhatsApp and prepare a message to Mom.</Prompt>
                </div>
                <Button className="mt-4 w-full" disabled={!ready} onClick={() => navigate("/")}>
                  Open Chat
                </Button>
              </div>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}

function ToolRow({ tool, enabled, required = false }: { tool?: ToolSet; enabled: boolean; required?: boolean }) {
  const label = tool?.name || tool?.id || "Unknown tool";
  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3",
        enabled ? "border-emerald-500/20 bg-emerald-500/10" : "border-zinc-800 bg-zinc-950/40"
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-foreground">{label}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{required ? "Required" : "Recommended"}</div>
        </div>
        {enabled ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : <XCircle className="h-5 w-5 text-zinc-600" />}
      </div>
    </div>
  );
}

function StatusPanel({
  doctor,
  ready,
  requiredReady,
  recommendedReady,
  voiceReady,
  browserReady,
}: {
  doctor: DoctorStatus | null;
  ready: boolean;
  requiredReady: boolean;
  recommendedReady: number;
  voiceReady: boolean;
  browserReady: boolean;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">Readiness</h2>
      <div className="space-y-3">
        <StatusLine ok={Boolean(doctor?.installed)} label="Hermes installed" />
        <StatusLine ok={Boolean(doctor?.configured)} label="Model configured" />
        <StatusLine ok={requiredReady} label="Required tools enabled" />
        <StatusLine ok={recommendedReady >= 2} label={`${recommendedReady} recommended tools enabled`} />
        <StatusLine ok={browserReady} label="Website Chrome connected" />
        <StatusLine ok={voiceReady} label="Local voice ready" />
      </div>
      <div className={cn("mt-4 rounded-lg px-3 py-2 text-xs", ready ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-300")}>
        {ready ? "Hermes is ready for computer-use prompts." : "Finish the missing checks before expecting reliable computer-use behavior."}
      </div>
    </div>
  );
}

function NativeAutomationPanel() {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
        <Terminal className="h-4 w-4 text-primary" />
        Native App Automation
      </div>
      <div className="space-y-3 text-xs text-muted-foreground">
        <div className="rounded-lg bg-emerald-500/10 px-3 py-2 text-emerald-300">
          Notes note creation is enabled.
        </div>
        <p>
          Native app requests stay native. macOS may ask for Automation or Accessibility permission the first time Hermes controls an app.
        </p>
      </div>
    </div>
  );
}

function BrowserSessionPanel({
  status,
  loading,
  onConnect,
}: {
  status: ComputerUseStatus | null;
  loading: boolean;
  onConnect: () => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
        <Monitor className="h-4 w-4 text-primary" />
        Website Session
      </div>
      <div className="space-y-3 text-xs text-muted-foreground">
        <div className={cn("rounded-lg px-3 py-2", status?.chrome_connected ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-300")}>
          {status?.chrome_connected ? "Chrome is connected for explicit website tasks." : "Connect Chrome only when you want website control."}
        </div>
        <p>
          Browser tools are for prompts that name Chrome, a website, or a URL. Native apps such as Notes, Calendar, Music, FaceTime, and WhatsApp should use macOS automation.
        </p>
        {status?.profile_dir && (
          <p className="break-all text-[10px] text-muted-foreground/70">{status.profile_dir}</p>
        )}
        <Button className="w-full" variant="outline" onClick={onConnect} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {status?.chrome_connected ? "Reconnect Chrome" : "Connect Chrome"}
        </Button>
      </div>
    </div>
  );
}

function VoicePanel({ voice }: { voice: VoiceStatus | null }) {
  const active = voice?.engines.find((engine) => engine.id === voice.active_engine);
  const install = voice?.engines.find((engine) => !engine.available);
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
        <Mic className="h-4 w-4 text-primary" />
        Voice Control
      </div>
      {voice?.configured ? (
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="rounded-lg bg-emerald-500/10 px-3 py-2 text-emerald-300">
            Local STT: {active?.name || voice.active_engine}
          </div>
          <p>Use the mic in Chat. Audio is transcribed by the local backend before the command is sent to Hermes.</p>
        </div>
      ) : (
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="rounded-lg bg-amber-500/10 px-3 py-2 text-amber-300">
            Install a local speech model to use voice commands.
          </div>
          <Prompt>{install?.install_hint || "python3 -m pip install faster-whisper"}</Prompt>
          <p>Recommended on Apple Silicon: MLX Whisper. General fallback: faster-whisper.</p>
        </div>
      )}
    </div>
  );
}

function StatusLine({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <XCircle className="h-4 w-4 text-zinc-600" />}
    </div>
  );
}

function PermissionCard({
  name,
  detail,
  ok,
  onOpen,
}: {
  name: string;
  detail: string;
  ok: boolean | null;
  onOpen: () => Promise<void> | void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            {ok === true ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            ) : ok === false ? (
              <XCircle className="h-3.5 w-3.5 text-amber-400" />
            ) : (
              <Circle className="h-3.5 w-3.5 text-muted-foreground" />
            )}
            {name}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">{detail}</p>
        </div>
        <Button size="sm" variant="outline" onClick={onOpen}>
          Open
        </Button>
      </div>
    </div>
  );
}

function Prompt({ children }: { children: string }) {
  return <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2 font-mono text-[11px] text-zinc-300">{children}</div>;
}
