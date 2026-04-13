import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

interface UseSpeechToTextReturn {
  isListening: boolean;
  isTranscribing: boolean;
  transcript: string;
  error: string;
  startListening: () => Promise<void>;
  stopListening: () => Promise<string>;
  supported: boolean;
}

export function useSpeechToText(): UseSpeechToTextReturn {
  const [isListening, setIsListening] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingStartedAtRef = useRef(0);
  const stopPromiseRef = useRef<{
    resolve: (value: string) => void;
    reject: (reason?: unknown) => void;
  } | null>(null);

  const supported =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined";

  const cleanup = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  const startListening = useCallback(async () => {
    if (!supported || isListening) return;

    setError("");
    setTranscript("");
    chunksRef.current = [];
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    streamRef.current = stream;

    const mimeType = selectRecordingMimeType();
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    recorderRef.current = recorder;
    recordingStartedAtRef.current = Date.now();

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };

    recorder.onerror = () => {
      setError("Microphone recording failed.");
      setIsListening(false);
      cleanup();
    };

    recorder.onstop = async () => {
      setIsListening(false);
      setIsTranscribing(true);
      cleanup();
      try {
        if (!chunksRef.current.length) {
          throw new Error("No microphone audio was captured. Hold Option+Command a little longer.");
        }
        const audio = new Blob(chunksRef.current, {
          type: mimeType || chunksRef.current[0]?.type || "audio/mp4",
        });
        if (audio.size < 1024) {
          throw new Error("The voice command was too short to transcribe. Hold Option+Command a little longer.");
        }
        const result = await api.transcribeVoice(audio);
        const text = result.text.trim();
        setTranscript(text);
        stopPromiseRef.current?.resolve(text);
      } catch (err: any) {
        const message = err?.message || "Could not transcribe audio locally.";
        setError(message);
        stopPromiseRef.current?.reject(err);
      } finally {
        setIsTranscribing(false);
        stopPromiseRef.current = null;
      }
    };

    recorder.start(250);
    setIsListening(true);
  }, [cleanup, isListening, supported]);

  const stopListening = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return transcript;

    const elapsedMs = Date.now() - recordingStartedAtRef.current;
    if (elapsedMs < 450) {
      await new Promise((resolve) => setTimeout(resolve, 450 - elapsedMs));
    }

    const stopped = new Promise<string>((resolve, reject) => {
      stopPromiseRef.current = { resolve, reject };
    });
    recorder.requestData();
    recorder.stop();
    return stopped;
  }, [transcript]);

  return { isListening, isTranscribing, transcript, error, startListening, stopListening, supported };
}

function selectRecordingMimeType() {
  const candidates = [
    "audio/mp4;codecs=mp4a.40.2",
    "audio/mp4",
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

interface UseTextToSpeechReturn {
  speak: (text: string) => void;
  stop: () => void;
  isSpeaking: boolean;
  supported: boolean;
}

export function useTextToSpeech(): UseTextToSpeechReturn {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;

  const speak = useCallback(
    (text: string) => {
      if (!supported) return;

      const clean = text
        .replace(/```[\s\S]*?```/g, "code block")
        .replace(/`[^`]+`/g, (m) => m.slice(1, -1))
        .replace(/[#*_~>\[\]()]/g, "")
        .replace(/\n{2,}/g, ". ")
        .replace(/\n/g, " ")
        .trim();

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(clean);
      utterance.rate = 1.05;
      utterance.pitch = 1;

      const voices = window.speechSynthesis.getVoices();
      const preferred = voices.find(
        (v) => v.name.includes("Samantha") || v.name.includes("Daniel")
      );
      if (preferred) utterance.voice = preferred;

      utterance.onstart = () => setIsSpeaking(true);
      utterance.onend = () => setIsSpeaking(false);
      utterance.onerror = () => setIsSpeaking(false);

      window.speechSynthesis.speak(utterance);
    },
    [supported]
  );

  const stop = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, [supported]);

  return { speak, stop, isSpeaking, supported };
}

export function useAgentTalkBack() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState("");

  const stop = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setIsSpeaking(false);
  }, []);

  const speak = useCallback(
    async (text: string) => {
      const clean = text.trim();
      if (!clean) return;
      stop();
      setError("");
      try {
        const audio = await api.synthesizeVoice(clean);
        const url = URL.createObjectURL(audio);
        objectUrlRef.current = url;
        const player = new Audio(url);
        audioRef.current = player;
        setIsSpeaking(true);
        await player.play();
        await new Promise<void>((resolve) => {
          player.onended = () => {
            stop();
            resolve();
          };
          player.onerror = () => {
            setError("Could not play assistant voice.");
            stop();
            resolve();
          };
        });
      } catch (err: any) {
        setError(err?.message || "Could not synthesize assistant voice.");
        setIsSpeaking(false);
      }
    },
    [stop]
  );

  useEffect(() => stop, [stop]);

  return { speak, stop, isSpeaking, error };
}
