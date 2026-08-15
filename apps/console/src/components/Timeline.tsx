import type { FirstDeviation, JourneySegment } from "../types";
import { PHASE_ORDER } from "../types";

interface Props {
  segments: JourneySegment[];
  currentPhase: string;
  deviation: FirstDeviation | null | undefined;
  cursorMs: number;
}

export function Timeline({ segments, currentPhase, deviation, cursorMs }: Props) {
  const reached = new Set(segments.map((s) => s.phase));
  const byPhase = new Map(segments.map((s) => [s.phase, s]));

  return (
    <div className="border-b border-ink-600 bg-ink-900 px-4 py-3">
      <div className="mb-2 flex items-center justify-between text-2xs uppercase tracking-[0.14em] text-slate-500">
        <span>Journey reconstruction</span>
        {deviation ? (
          <span className="text-amber-400">
            First deviation · {deviation.phase} · {deviation.type.replaceAll("_", " ").toLowerCase()} at{" "}
            {deviation.timestamp_ms} ms
          </span>
        ) : (
          <span>Expected vs observed phase occupancy</span>
        )}
      </div>
      <div className="flex gap-1 overflow-x-auto pb-1">
        {PHASE_ORDER.filter((p) => p !== "MAINTENANCE").map((phase) => {
          const segment = byPhase.get(phase);
          const isDev = deviation?.phase === phase;
          const isNow = currentPhase === phase;
          const seen = reached.has(phase);
          return (
            <div
              key={phase}
              className={`min-w-[5.4rem] flex-1 rounded border px-1.5 py-1 ${
                isDev
                  ? "border-amber-400 bg-amber-500/15 animate-pulseMark"
                  : isNow
                    ? "border-wire bg-wire/10"
                    : seen
                      ? "border-ink-500 bg-ink-800"
                      : "border-ink-700 bg-ink-900 text-slate-600"
              }`}
            >
              <div className="truncate font-mono text-2xs">{phase.replaceAll("_", " ")}</div>
              <div className="font-mono text-2xs text-slate-400">
                {segment
                  ? `${(segment.start_ms / 1000).toFixed(1)}s`
                  : seen
                    ? "·"
                    : cursorMs > 0
                      ? "—"
                      : ""}
              </div>
            </div>
          );
        })}
      </div>
      {deviation ? (
        <p className="mt-2 max-w-5xl text-xs text-amber-100/90">{deviation.statement}</p>
      ) : null}
    </div>
  );
}
