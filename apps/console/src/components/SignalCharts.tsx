import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChannelQuality, FirstDeviation, SignalFrame } from "../types";
import { SIGNAL_KEYS } from "../types";

interface Props {
  frames: SignalFrame[];
  cursorMs: number;
  deviation?: FirstDeviation | null;
  quality: ChannelQuality[];
}

export function SignalCharts({ frames, cursorMs, deviation, quality }: Props) {
  const visible = frames.filter((f) => f.timestamp_ms <= cursorMs);
  const step = Math.max(1, Math.floor(visible.length / 220));
  const data = visible.filter((_, i) => i % step === 0).map((f) => ({
    t: f.timestamp_ms / 1000,
    ...f.signals,
  }));
  const defects = quality.filter((c) => c.defects.length);

  return (
    <section className="panel overflow-hidden">
      <header className="flex items-center justify-between border-b border-ink-600 px-3 py-2 text-2xs uppercase tracking-[0.14em] text-slate-500">
        <span>Synchronized signals</span>
        {defects.length ? (
          <span className="normal-case tracking-normal text-violet-300">
            quality: {defects.map((d) => `${d.channel} (${d.defects.join(", ")})`).join(" · ")}
          </span>
        ) : (
          <span className="normal-case tracking-normal">20 ms samples · downsample for display only</span>
        )}
      </header>
      <div className="grid grid-cols-2 gap-0 lg:grid-cols-4 xl:grid-cols-7">
        {SIGNAL_KEYS.map((spec) => (
          <div key={spec.key} className="border-r border-t border-ink-700 p-1 last:border-r-0">
            <div className="px-1 font-mono text-2xs text-slate-400">
              {spec.label}
              {spec.unit ? ` · ${spec.unit}` : ""}
            </div>
            <div className="h-20">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <XAxis dataKey="t" hide />
                  <YAxis hide domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{
                      background: "#101822",
                      border: "1px solid #243346",
                      fontSize: 11,
                    }}
                    labelFormatter={(v) => `${Number(v).toFixed(2)} s`}
                  />
                  <Line
                    type="monotone"
                    dataKey={spec.key}
                    stroke="#22c3d6"
                    dot={false}
                    strokeWidth={1.2}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        ))}
      </div>
      {deviation ? (
        <div className="border-t border-ink-700 px-3 py-1 font-mono text-2xs text-amber-300">
          marker @ {(deviation.timestamp_ms / 1000).toFixed(2)} s · {deviation.phase}
        </div>
      ) : null}
    </section>
  );
}
