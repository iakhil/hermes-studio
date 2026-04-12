import { useCallback, useRef, useState } from "react";
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
  const chunksRef = useRef<BlobPart[]>([]);
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

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    recorderRef.current = recorder;

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
        const audio = new Blob(chunksRef.current, { type: mimeType });
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

    recorder.start();
    setIsListening(true);
  }, [cleanup, isListening, supported]);

  const stopListening = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return transcript;

    const stopped = new Promise<string>((resolve, reject) => {
      stopPromiseRef.current = { resolve, reject };
    });
    recorder.stop();
    return stopped;
  }, [transcript]);

  return { isListening, isTranscribing, transcript, error, startListening, stopListening, supported };
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
