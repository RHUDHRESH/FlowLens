import type { IncidentEnvelope } from "../types";

const DECISION_STYLE: Record<string, string> = {
  HEALTHY: "bg-emerald-700 text-emerald-50",
  KNOWN_FAULT: "bg-sky-700 text-sky-50",
  UNKNOWN_FAULT: "bg-amber-600 text-amber-50",
  SENSOR_CHECK: "bg-violet-700 text-violet-50",
  HUMAN_REVIEW: "bg-amber-700 text-amber-50",
  INSUFFICIENT_DATA: "bg-stone-600 text-stone-50",
  OUT_OF_SCOPE: "bg-stone-600 text-stone-50",
};

interface Props {
  envelope: IncidentEnvelope | null;
  scenarioTitle: string;
  currentPhase: string;
  cursorMs: number;
  durationMs: number;
  streaming: boolean;
}

export function Header({
  envelope,
  scenarioTitle,
  currentPhase,
  cursorMs,
  durationMs,
  streaming,
}: Props) {
  const decision = envelope?.decision ?? (streaming ? "RECONSTRUCTING" : "STANDBY");
  const style = DECISION_STYLE[decision] ?? "bg-ink-600 text-slate-200";

  return (
    <header className="flex items-center gap-4 border-b border-ink-600 bg-ink-900 px-4 py-2">
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <h1 className="text-sm font-semibold tracking-tight text-white">FlowLens RCA Lab</h1>
          <span className="text-2xs uppercase tracking-[0.14em] text-wire">read-only</span>
        </div>
        <p className="truncate text-2xs text-slate-400">
          PS13 · evidence-first isolation · never commands, resets, or returns to service
        </p>
      </div>

      <div className="ml-auto flex items-center gap-3 text-2xs">
        <Meta label="asset" value={envelope?.asset_id ?? "demo_elevator_01"} />
        <Meta label="journey" value={envelope?.journey_id ?? "—"} />
        <Meta label="scenario" value={scenarioTitle || "—"} />
        <Meta label="phase" value={currentPhase} accent />
        <Meta
          label="t"
          value={`${(cursorMs / 1000).toFixed(1)} / ${(durationMs / 1000).toFixed(1)} s`}
        />
        <span className={`rounded px-2 py-1 text-2xs font-semibold tracking-wide ${style}`}>
          {decision.replaceAll("_", " ")}
        </span>
      </div>
    </header>
  );
}

function Meta({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="hidden sm:block">
      <div className="uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`font-mono ${accent ? "text-wire" : "text-slate-200"}`}>{value}</div>
    </div>
  );
}
