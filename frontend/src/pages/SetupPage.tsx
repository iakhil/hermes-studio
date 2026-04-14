import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { apiBaseUrl } from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Provider, Model, TtsStatus, VoiceStatus } from "@/lib/types";
import {
  CheckCircle2,
  XCircle,
  ArrowRight,
  ArrowLeft,
  Loader2,
  Sparkles,
  Zap,
  Eye,
  EyeOff,
  ExternalLink,
  Terminal,
  Check,
  Download,
  Mic,
  Volume2,
} from "lucide-react";

type Step = "check" | "provider" | "apikey" | "model" | "test" | "voice" | "done";

const STEPS: Step[] = ["check", "provider", "apikey", "model", "test", "voice", "done"];

const STEP_TITLES: Record<Step, string> = {
  check: "Check Installation",
  provider: "Choose Provider",
  apikey: "API Key",
  model: "Select Model",
  test: "Test Connection",
  voice: "Local Voice",
  done: "Ready!",
};

const DEFAULT_VOICE_MODELS = [
  {
    id: "base.en",
    name: "Base English",
    filename: "ggml-base.en.bin",
    url: "",
    detail: "Recommended balance for voice commands.",
  },
  {
    id: "tiny.en",
    name: "Tiny English",
    filename: "ggml-tiny.en.bin",
    url: "",
    detail: "Fastest local model. Good for quick commands.",
  },
];

export function SetupPage() {
  const [step, setStep] = useState<Step>("check");
  const [direction, setDirection] = useState(1);
  const navigate = useNavigate();

  // State
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [testResult, setTestResult] = useState<{
    success: boolean;
    response?: string;
    latency_ms?: number;
    error?: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installLog, setInstallLog] = useState<string[]>([]);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [ttsStatus, setTtsStatus] = useState<TtsStatus | null>(null);
  const [voiceModel, setVoiceModel] = useState("base.en");
  const [voiceInstalling, setVoiceInstalling] = useState(false);
  const [voiceInstallLog, setVoiceInstallLog] = useState<string[]>([]);
  const [setupError, setSetupError] = useState("");

  const stepIndex = STEPS.indexOf(step);

  const goTo = (s: Step) => {
    const newIndex = STEPS.indexOf(s);
    setDirection(newIndex > stepIndex ? 1 : -1);
    setStep(s);
  };

  // Check installation on mount
  useEffect(() => {
    checkInstall();
  }, []);

  useEffect(() => {
    if (step === "voice") {
      void loadVoiceState();
    }
  }, [step]);

  async function checkInstall() {
    setLoading(true);
    try {
      const res = await api.checkInstall();
      setInstalled(res.installed);
      setVersion(res.version || "");
    } catch {
      setInstalled(false);
    }
    setLoading(false);
  }

  async function installHermes() {
    setInstalling(true);
    setInstallLog([]);
    try {
      const res = await fetch(`${apiBaseUrl()}/setup/install`, { method: "POST" });

      if (!res.ok) {
        setInstallLog([`Backend returned ${res.status}. Is the backend server running? (make dev-backend)`]);
        setInstalling(false);
        return;
      }

      await readEventStream(res, async (data) => {
        if (data === "[DONE]") {
          setInstalling(false);
          const installedNow = await refreshInstallState();
          if (installedNow) {
            setInstallLog((prev) => [...prev, "Hermes Agent detected. Continue to provider setup."]);
          }
          return false;
        }
        if (data.startsWith("[ERROR]")) {
          setInstallLog((prev) => [...prev, data]);
          setInstalling(false);
          await refreshInstallState();
          return false;
        }
        setInstallLog((prev) => [...prev.slice(-100), data]);
        return true;
      });
      // Stream ended without [DONE] — re-check anyway
      setInstalling(false);
      await refreshInstallState();
    } catch (e: any) {
      setInstallLog((prev) => [
        ...prev,
        `Connection error: ${e.message}. Make sure the backend is running (make dev-backend).`,
      ]);
      setInstalling(false);
      await refreshInstallState();
    }
  }

  async function loadVoiceState() {
    try {
      const [voice, tts] = await Promise.all([api.voiceStatus(), api.ttsStatus()]);
      setVoiceStatus(voice);
      setTtsStatus(tts);
      if (!voice.install_options?.some((option) => option.id === voiceModel)) {
        setVoiceModel(voice.install_options?.[0]?.id || "base.en");
      }
    } catch (e: any) {
      setSetupError(e.message || "Could not load local voice status.");
    }
  }

  async function installLocalVoice() {
    setVoiceInstalling(true);
    setVoiceInstallLog([]);
    setSetupError("");
    try {
      const res = await fetch(`${apiBaseUrl()}/voice/stt/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine: "whisper.cpp", model: voiceModel }),
      });
      if (!res.ok) {
        setVoiceInstallLog([`Backend returned ${res.status}.`]);
        setVoiceInstalling(false);
        return;
      }

      await readEventStream(res, async (data) => {
        if (data === "[DONE]") {
          setVoiceInstalling(false);
          await loadVoiceState();
          return false;
        }
        if (data.startsWith("[ERROR]")) {
          setVoiceInstallLog((prev) => [...prev, data]);
          setVoiceInstalling(false);
          await loadVoiceState();
          return false;
        }
        setVoiceInstallLog((prev) => [...prev.slice(-100), data]);
        return true;
      });
      setVoiceInstalling(false);
      await loadVoiceState();
    } catch (e: any) {
      setVoiceInstallLog((prev) => [...prev, `Connection error: ${e.message}`]);
      setVoiceInstalling(false);
      await loadVoiceState();
    }
  }

  async function refreshInstallState() {
    try {
      const res = await api.checkInstall();
      setInstalled(res.installed);
      setVersion(res.version || "");
      return res.installed;
    } catch {
      setInstalled(false);
      return false;
    }
  }

  async function loadProviders() {
    try {
      const res = await api.getProviders();
      setProviders(res);
    } catch {
      setProviders([]);
    }
  }

  async function loadModels(provider: string) {
    setLoading(true);
    try {
      const res = await api.getModels(provider);
      setModels(res);
    } catch {
      setModels([]);
    }
    setLoading(false);
  }

  async function configureProvider() {
    setLoading(true);
    setSetupError("");
    try {
      const res = await api.configureProvider({
        provider: selectedProvider,
        api_key: apiKey || undefined,
      });
      if (!res.success) {
        setSetupError((res as any).error || "Could not save provider configuration.");
        setLoading(false);
        return;
      }
      await loadModels(selectedProvider);
      goTo("model");
    } catch (e: any) {
      setSetupError(e.message || "Could not save provider configuration.");
    }
    setLoading(false);
  }

  async function selectModel() {
    setLoading(true);
    setSetupError("");
    try {
      const res = await api.selectModel(selectedModel, selectedProvider);
      if (!res.success) {
        setSetupError((res as any).error || "Could not save model selection.");
        setLoading(false);
        return;
      }
      goTo("test");
    } catch (e: any) {
      setSetupError(e.message || "Could not save model selection.");
    }
    setLoading(false);
  }

  async function testConnection() {
    setLoading(true);
    setTestResult(null);
    try {
      const res = await api.testConnection();
      setTestResult(res);
    } catch (e: any) {
      setTestResult({ success: false, error: e.message });
    }
    setLoading(false);
  }

  const providerNeedsKey = providers.find((p) => p.id === selectedProvider)?.requires_key ?? true;

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-6 py-10">
        {/* Progress */}
        <div className="mb-10 flex items-center justify-center gap-2">
          {STEPS.map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-xs font-medium transition-all",
                  i < stepIndex
                    ? "bg-primary text-primary-foreground"
                    : i === stepIndex
                    ? "bg-primary/20 text-primary border border-primary/40"
                    : "bg-zinc-800 text-muted-foreground"
                )}
              >
                {i < stepIndex ? <Check className="h-4 w-4" /> : i + 1}
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={cn(
                    "h-0.5 w-8 rounded-full transition-colors",
                    i < stepIndex ? "bg-primary" : "bg-zinc-800"
                  )}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step content */}
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, x: direction * 30 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: direction * -30 }}
            transition={{ duration: 0.2 }}
          >
            {step === "check" && (
              <StepCard
                title="Check Installation"
                description="Let's make sure Hermes Agent is installed on your system."
              >
                {loading ? (
                  <div className="flex items-center gap-3 py-8 justify-center">
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                    <span className="text-sm text-muted-foreground">Checking installation...</span>
                  </div>
                ) : installed === null ? null : installed ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-4 py-3">
                      <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                      <div>
                        <p className="text-sm font-medium text-emerald-400">Hermes Agent is installed</p>
                        {version && (
                          <p className="text-xs text-muted-foreground">Version: {version}</p>
                        )}
                      </div>
                    </div>
                    <Button
                      onClick={() => {
                        loadProviders();
                        goTo("provider");
                      }}
                      className="w-full"
                    >
                      Continue
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {!installing && installLog.length === 0 && (
                      <>
                        <div className="flex items-center gap-3 rounded-lg bg-amber-500/10 border border-amber-500/20 px-4 py-3">
                          <Download className="h-5 w-5 text-amber-400" />
                          <div>
                            <p className="text-sm font-medium text-amber-400">
                              Hermes Agent not found
                            </p>
                            <p className="text-xs text-muted-foreground">
                              No worries — we'll install it for you.
                            </p>
                          </div>
                        </div>

                        <Button onClick={installHermes} className="w-full">
                          <Download className="h-4 w-4" />
                          Install Hermes Agent
                        </Button>
                      </>
                    )}

                    {(installing || installLog.length > 0) && (
                      <>
                        <div className="rounded-lg bg-zinc-950 border border-zinc-800 p-1">
                          <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800">
                            {installing ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                            ) : installLog.some((l) => l.startsWith("[ERROR]")) ? (
                              <XCircle className="h-3.5 w-3.5 text-destructive" />
                            ) : (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                            )}
                            <span className="text-xs text-muted-foreground font-mono">
                              {installing ? "Installing..." : "Installation complete"}
                            </span>
                          </div>
                          <div className="max-h-48 overflow-y-auto p-3 font-mono text-xs text-zinc-400 space-y-0.5">
                            {installLog.map((line, i) => (
                              <div key={i} className={cn(
                                line.startsWith("[ERROR]") && "text-destructive"
                              )}>{line}</div>
                            ))}
                            {installing && (
                              <div className="flex items-center gap-1.5 text-primary">
                                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                                <span>waiting for output...</span>
                              </div>
                            )}
                          </div>
                        </div>

                        {!installing && installLog.some((l) => l.startsWith("[ERROR]")) && (
                          <Button onClick={installHermes} variant="outline" className="w-full">
                            Retry Installation
                          </Button>
                        )}

                        {!installing && installed && (
                          <Button
                            onClick={() => {
                              loadProviders();
                              goTo("provider");
                            }}
                            className="w-full"
                          >
                            Continue
                            <ArrowRight className="h-4 w-4" />
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                )}
              </StepCard>
            )}

            {step === "provider" && (
              <StepCard
                title="Choose Your Provider"
                description="Select which AI provider you'd like to use with Hermes."
              >
                {setupError && <SetupError message={setupError} />}
                <div className="grid gap-3">
                  {providers.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => setSelectedProvider(p.id)}
                      className={cn(
                        "flex items-center gap-4 rounded-xl border px-4 py-4 text-left transition-all cursor-pointer",
                        selectedProvider === p.id
                          ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                          : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-700"
                      )}
                    >
                      <ProviderIcon provider={p.id} />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{p.name}</span>
                          {p.configured && <Badge variant="success">Configured</Badge>}
                          {!p.requires_key && (
                            <Badge variant="secondary">No key needed</Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">{p.description}</p>
                      </div>
                      {selectedProvider === p.id && (
                        <CheckCircle2 className="h-5 w-5 text-primary shrink-0" />
                      )}
                    </button>
                  ))}
                </div>

                <div className="flex gap-3 mt-6">
                  <Button variant="outline" onClick={() => goTo("check")}>
                    <ArrowLeft className="h-4 w-4" />
                    Back
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={!selectedProvider}
                    onClick={() => {
                      if (!providerNeedsKey) {
                        configureProvider();
                      } else {
                        goTo("apikey");
                      }
                    }}
                  >
                    Continue
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </StepCard>
            )}

            {step === "apikey" && (
              <StepCard
                title="Enter API Key"
                description={`Provide your ${providers.find((p) => p.id === selectedProvider)?.name || ""} API key.`}
              >
                {setupError && <SetupError message={setupError} />}
                <div className="space-y-4">
                  <div className="relative">
                    <Input
                      type={showKey ? "text" : "password"}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-..."
                      className="pr-10 font-mono"
                    />
                    <button
                      onClick={() => setShowKey(!showKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
                    >
                      {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    Your key is stored locally in your Hermes config file. It never leaves your machine.
                  </p>
                </div>

                <div className="flex gap-3 mt-6">
                  <Button variant="outline" onClick={() => goTo("provider")}>
                    <ArrowLeft className="h-4 w-4" />
                    Back
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={!apiKey.trim() || loading}
                    onClick={configureProvider}
                  >
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        Save & Continue
                        <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
              </StepCard>
            )}

            {step === "model" && (
              <StepCard
                title="Select a Model"
                description="Choose which model Hermes should use."
              >
                {setupError && <SetupError message={setupError} />}
                <div className="grid gap-2">
                  {models.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => setSelectedModel(m.id)}
                      className={cn(
                        "flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all cursor-pointer",
                        selectedModel === m.id
                          ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                          : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-700"
                      )}
                    >
                      <Zap className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-medium">{m.name}</span>
                        <p className="text-xs text-muted-foreground font-mono truncate">{m.id}</p>
                      </div>
                      {m.context_length && (
                        <Badge variant="secondary" className="text-[10px] shrink-0">
                          {(m.context_length / 1000).toFixed(0)}k ctx
                        </Badge>
                      )}
                      {selectedModel === m.id && (
                        <CheckCircle2 className="h-4 w-4 text-primary shrink-0" />
                      )}
                    </button>
                  ))}
                </div>

                <div className="flex gap-3 mt-6">
                  <Button
                    variant="outline"
                    onClick={() => goTo(providerNeedsKey ? "apikey" : "provider")}
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Back
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={!selectedModel || loading}
                    onClick={selectModel}
                  >
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        Continue
                        <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
              </StepCard>
            )}

            {step === "test" && (
              <StepCard
                title="Test Connection"
                description="Let's verify everything works by sending a test message."
              >
                <div className="space-y-4">
                  {!testResult && !loading && (
                    <Button onClick={testConnection} className="w-full">
                      <Zap className="h-4 w-4" />
                      Run Connection Test
                    </Button>
                  )}

                  {loading && (
                    <div className="flex items-center gap-3 py-8 justify-center">
                      <Loader2 className="h-5 w-5 animate-spin text-primary" />
                      <span className="text-sm text-muted-foreground">
                        Testing connection...
                      </span>
                    </div>
                  )}

                  {testResult && (
                    <div
                      className={cn(
                        "rounded-lg border px-4 py-4",
                        testResult.success
                          ? "bg-emerald-500/10 border-emerald-500/20"
                          : "bg-destructive/10 border-destructive/20"
                      )}
                    >
                      <div className="flex items-center gap-2 mb-2">
                        {testResult.success ? (
                          <>
                            <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                            <span className="text-sm font-medium text-emerald-400">
                              Connection successful!
                            </span>
                            {testResult.latency_ms && (
                              <Badge variant="success">{testResult.latency_ms}ms</Badge>
                            )}
                          </>
                        ) : (
                          <>
                            <XCircle className="h-5 w-5 text-destructive" />
                            <span className="text-sm font-medium text-destructive">
                              Connection failed
                            </span>
                          </>
                        )}
                      </div>
                      {testResult.response && (
                        <p className="text-sm text-muted-foreground">{testResult.response}</p>
                      )}
                      {testResult.error && (
                        <p className="text-sm text-destructive/80">{testResult.error}</p>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex gap-3 mt-6">
                  <Button variant="outline" onClick={() => goTo("model")}>
                    <ArrowLeft className="h-4 w-4" />
                    Back
                  </Button>
                  {testResult?.success && (
                    <Button className="flex-1" onClick={() => goTo("voice")}>
                      Continue
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  )}
                  {testResult && !testResult.success && (
                    <Button variant="outline" className="flex-1" onClick={testConnection}>
                      Retry
                    </Button>
                  )}
                </div>
              </StepCard>
            )}

            {step === "voice" && (
              <StepCard
                title="Set Up Local Voice"
                description="Install local speech-to-text so hotkey voice commands work in the packaged app."
              >
                {setupError && <SetupError message={setupError} />}
                <div className="space-y-4">
                  <div
                    className={cn(
                      "rounded-lg border px-4 py-4",
                      voiceStatus?.configured
                        ? "border-emerald-500/20 bg-emerald-500/10"
                        : "border-amber-500/20 bg-amber-500/10"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      {voiceStatus?.configured ? (
                        <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-400" />
                      ) : (
                        <Mic className="mt-0.5 h-5 w-5 text-amber-300" />
                      )}
                      <div>
                        <p
                          className={cn(
                            "text-sm font-medium",
                            voiceStatus?.configured ? "text-emerald-300" : "text-amber-300"
                          )}
                        >
                          {voiceStatus?.configured ? "Local speech-to-text is ready" : "Local speech-to-text is not configured"}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {voiceStatus?.configured
                            ? `Active engine: ${voiceStatus.active_engine || "local voice"}`
                            : "Hermes Studio can install whisper.cpp and keep the model on this Mac."}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-4">
                    <div className="flex items-start gap-3">
                      <Volume2 className="mt-0.5 h-5 w-5 text-primary" />
                      <div>
                        <p className="text-sm font-medium">Talk-back</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {ttsStatus?.configured
                            ? `Ready with ${ttsStatus.active_engine || "system voice"}.`
                            : "Hermes Studio can still run without talk-back. macOS system speech is used when available."}
                        </p>
                      </div>
                    </div>
                  </div>

                  {!voiceStatus?.configured && (
                    <div className="space-y-3">
                      <div className="grid gap-2">
                        {(voiceStatus?.install_options || DEFAULT_VOICE_MODELS).map((option) => (
                          <button
                            key={option.id}
                            onClick={() => setVoiceModel(option.id)}
                            className={cn(
                              "flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all cursor-pointer",
                              voiceModel === option.id
                                ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                                : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-700"
                            )}
                          >
                            <Mic className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <div className="min-w-0 flex-1">
                              <span className="text-sm font-medium">{option.name}</span>
                              <p className="text-xs text-muted-foreground">{option.detail}</p>
                            </div>
                            {voiceModel === option.id && (
                              <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
                            )}
                          </button>
                        ))}
                      </div>

                      <Button onClick={installLocalVoice} disabled={voiceInstalling} className="w-full">
                        {voiceInstalling ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="h-4 w-4" />
                        )}
                        {voiceInstalling ? "Installing Local Voice..." : "Install Local Voice"}
                      </Button>
                    </div>
                  )}

                  {(voiceInstalling || voiceInstallLog.length > 0) && (
                    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-1">
                      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2">
                        {voiceInstalling ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                        ) : voiceInstallLog.some((l) => l.startsWith("[ERROR]")) ? (
                          <XCircle className="h-3.5 w-3.5 text-destructive" />
                        ) : (
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                        )}
                        <span className="font-mono text-xs text-muted-foreground">
                          {voiceInstalling ? "Installing local voice..." : "Local voice setup"}
                        </span>
                      </div>
                      <div className="max-h-48 space-y-0.5 overflow-y-auto p-3 font-mono text-xs text-zinc-400">
                        {voiceInstallLog.map((line, i) => (
                          <div key={i} className={cn(line.startsWith("[ERROR]") && "text-destructive")}>
                            {line}
                          </div>
                        ))}
                        {voiceInstalling && (
                          <div className="flex items-center gap-1.5 text-primary">
                            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                            <span>waiting for output...</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <div className="mt-6 flex gap-3">
                  <Button variant="outline" onClick={() => goTo("test")}>
                    <ArrowLeft className="h-4 w-4" />
                    Back
                  </Button>
                  <Button
                    variant={voiceStatus?.configured ? "default" : "outline"}
                    className="flex-1"
                    disabled={voiceInstalling}
                    onClick={() => goTo("done")}
                  >
                    {voiceStatus?.configured ? "Finish Setup" : "Skip Voice for Now"}
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </StepCard>
            )}

            {step === "done" && (
              <StepCard
                title="You're All Set!"
                description="Hermes Studio is configured and ready to use."
              >
                <div className="flex flex-col items-center py-6">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: "spring", duration: 0.5 }}
                    className="flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-purple-700 mb-6"
                  >
                    <Sparkles className="h-10 w-10 text-white" />
                  </motion.div>

                  <p className="text-sm text-muted-foreground text-center mb-6 max-w-sm">
                    Your Hermes Agent is configured with{" "}
                    <span className="text-foreground font-medium">{selectedModel}</span>.
                    Start chatting now!
                  </p>

                  <Button onClick={() => navigate("/")} className="w-full max-w-xs" size="lg">
                    <Sparkles className="h-4 w-4" />
                    Start Chatting
                  </Button>
                </div>
              </StepCard>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

async function readEventStream(
  res: Response,
  onData: (data: string) => boolean | void | Promise<boolean | void>
) {
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("Could not read response stream.");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const event of events) {
      const data = event
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.replace(/^data:\s?/, ""))
        .join("\n");
      if (!data) continue;
      const keepGoing = await onData(data);
      if (keepGoing === false) {
        await reader.cancel();
        return;
      }
    }
  }

  const trailing = buffer.trim();
  if (trailing) {
    const data = trailing
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.replace(/^data:\s?/, ""))
      .join("\n");
    if (data) await onData(data);
  }
}

function StepCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/30">
      <CardHeader>
        <CardTitle className="text-lg">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function SetupError({ message }: { message: string }) {
  return (
    <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      {message}
    </div>
  );
}

function ProviderIcon({ provider }: { provider: string }) {
  const colors: Record<string, string> = {
    openrouter: "from-orange-500 to-red-500",
    openai: "from-emerald-400 to-green-600",
    anthropic: "from-amber-400 to-orange-600",
    nous: "from-violet-500 to-purple-700",
    ollama: "from-blue-400 to-cyan-600",
  };

  const letters: Record<string, string> = {
    openrouter: "OR",
    openai: "AI",
    anthropic: "A",
    nous: "N",
    ollama: "OL",
  };

  return (
    <div
      className={cn(
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br text-white text-xs font-bold",
        colors[provider] || "from-zinc-500 to-zinc-700"
      )}
    >
      {letters[provider] || "?"}
    </div>
  );
}
