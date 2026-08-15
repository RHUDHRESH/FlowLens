import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CausalGraph } from "./components/CausalGraph";
import { Controls } from "./components/Controls";
import { EventList } from "./components/EventList";
import { Header } from "./components/Header";
import { HypothesisPanel } from "./components/HypothesisPanel";
import { SignalCharts } from "./components/SignalCharts";
import { Timeline } from "./components/Timeline";
import {
  createRun,
  fetchDiagnosis,
  fetchEvents,
  fetchScenarios,
  openStream,
  pauseRun,
  reportUrl,
  resetRun,
  resumeRun,
  stepRun,
} from "./api";
import type {
  CreateRunResponse,
  DemoButton,
  IncidentEnvelope,
  JourneyEvent,
  ScenarioInfo,
  SignalFrame,
  StreamMessage,
} from "./types";

export default function App() {
  const [buttons, setButtons] = useState<DemoButton[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [run, setRun] = useState<CreateRunResponse | null>(null);
  const [events, setEvents] = useState<JourneyEvent[]>([]);
  const [frames, setFrames] = useState<SignalFrame[]>([]);
  const [cursorMs, setCursorMs] = useState(0);
  const [envelope, setEnvelope] = useState<IncidentEnvelope | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetchScenarios()
      .then((payload) => {
        setButtons(payload.demo_buttons);
        setScenarios(payload.scenarios);
        if (payload.demo_buttons[0]) setActiveId(payload.demo_buttons[0].scenario_id);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const stopSocket = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    setStreaming(false);
  }, []);

  useEffect(() => () => stopSocket(), [stopSocket]);

  const scenarioTitle = useMemo(() => {
    const match = scenarios.find((s) => s.scenario_id === activeId);
    return match?.title ?? activeId ?? "";
  }, [scenarios, activeId]);

  const currentPhase = useMemo(() => {
    if (envelope) {
      const live = envelope.journey.filter((s) => s.start_ms <= cursorMs);
      return live.at(-1)?.phase ?? envelope.terminal_phase ?? "IDLE";
    }
    const last = events.filter((e) => e.event_type === "PHASE_ENTERED" && e.timestamp_ms <= cursorMs).at(-1);
    return typeof last?.value === "string" ? last.value : "IDLE";
  }, [envelope, cursorMs, events]);

  const loadSlice = useCallback(async (runId: string, until: number) => {
    const payload = await fetchEvents(runId, until);
    setEvents(payload.events);
    setFrames(payload.frames);
    setCursorMs(until);
  }, []);

  const startStream = useCallback(
    (created: CreateRunResponse) => {
      stopSocket();
      setEvents([]);
      setFrames([]);
      setCursorMs(0);
      setEnvelope(null);
      const socket = openStream(created.run_id);
      socketRef.current = socket;
      setStreaming(true);
      socket.onmessage = (message) => {
        const payload = JSON.parse(message.data) as StreamMessage;
        if (payload.type === "batch") {
          setEvents((prev) => prev.concat(payload.events));
          setFrames((prev) => prev.concat(payload.frames));
          setCursorMs(payload.to_ms);
        } else if (payload.type === "diagnosis") {
          setEnvelope(payload.envelope);
        } else if (payload.type === "complete") {
          setStreaming(false);
        } else if (payload.type === "error") {
          setError(payload.detail);
          setStreaming(false);
        }
      };
      socket.onerror = () => {
        setError("Stream closed unexpectedly");
        setStreaming(false);
      };
    },
    [stopSocket],
  );

  const onSelect = useCallback(
    (scenarioId: string) => {
      stopSocket();
      setActiveId(scenarioId);
      setRun(null);
      setEvents([]);
      setFrames([]);
      setCursorMs(0);
      setEnvelope(null);
      setError(null);
    },
    [stopSocket],
  );

  const onRun = useCallback(async () => {
    if (!activeId) return;
    setError(null);
    try {
      const created = await createRun(activeId, false);
      setRun(created);
      startStream(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [activeId, startStream]);

  const onPause = useCallback(async () => {
    if (!run) return;
    await pauseRun(run.run_id);
  }, [run]);

  const onStep = useCallback(async () => {
    if (!run) return;
    stopSocket();
    const stepped = await stepRun(run.run_id, 400);
    await loadSlice(run.run_id, stepped.cursor_ms);
    if (stepped.complete) {
      setEnvelope(await fetchDiagnosis(run.run_id));
    }
  }, [run, stopSocket, loadSlice]);

  const onReset = useCallback(async () => {
    stopSocket();
    if (run) await resetRun(run.run_id);
    setEvents([]);
    setFrames([]);
    setCursorMs(0);
    setEnvelope(null);
  }, [run, stopSocket]);

  const onExport = useCallback(() => {
    if (!envelope) return;
    window.open(reportUrl(envelope.incident_id), "_blank", "noopener,noreferrer");
  }, [envelope]);

  const onResumeIfPaused = useCallback(async () => {
    if (!run) return;
    await resumeRun(run.run_id);
  }, [run]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-ink-950 text-slate-200">
      <Header
        envelope={envelope}
        scenarioTitle={scenarioTitle}
        currentPhase={currentPhase}
        cursorMs={cursorMs}
        durationMs={run?.duration_ms ?? 0}
        streaming={streaming}
      />
      <Controls
        buttons={buttons}
        activeId={activeId}
        busy={streaming}
        canStep={Boolean(run) && !streaming}
        canExport={Boolean(envelope)}
        onSelect={onSelect}
        onRun={() => {
          void onRun();
        }}
        onPause={() => {
          void onPause();
        }}
        onStep={() => {
          void onStep();
        }}
        onReset={() => {
          void onReset();
        }}
        onExport={onExport}
      />
      {error ? (
        <div className="border-b border-rose-900 bg-rose-950/60 px-4 py-1 text-xs text-rose-200">{error}</div>
      ) : null}
      <Timeline
        segments={envelope?.journey ?? []}
        currentPhase={currentPhase}
        deviation={envelope?.first_deviation}
        cursorMs={cursorMs}
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[20rem_minmax(0,1fr)_24rem]">
        <EventList events={events} alarms={envelope?.alarms ?? []} cursorMs={cursorMs} />
        <CausalGraph leading={envelope?.top_hypotheses[0] ?? null} deviation={envelope?.first_deviation} />
        <HypothesisPanel envelope={envelope} />
      </div>
      <div className="p-2 pt-0">
        <SignalCharts
          frames={frames}
          cursorMs={cursorMs}
          deviation={envelope?.first_deviation}
          quality={envelope?.channel_quality ?? []}
        />
      </div>
      <footer className="flex items-center justify-between px-4 py-1 text-2xs text-slate-500">
        <span>
          Simulated evidence laboratory · not a field installation · not a safety controller
        </span>
        {streaming ? (
          <button type="button" className="text-wire" onClick={() => void onResumeIfPaused()}>
            streaming
          </button>
        ) : (
          <span>advisory only</span>
        )}
      </footer>
    </div>
  );
}
