import type { JourneyEvent } from "../types";

interface Props {
  events: JourneyEvent[];
  alarms: string[];
  cursorMs: number;
}

export function EventList({ events, alarms, cursorMs }: Props) {
  const visible = events.filter((e) => e.timestamp_ms <= cursorMs).slice(-80);
  return (
    <section className="panel flex min-h-0 flex-col overflow-hidden">
      <header className="border-b border-ink-600 px-3 py-2 text-2xs uppercase tracking-[0.14em] text-slate-500">
        Events and alarms
      </header>
      {alarms.length > 0 ? (
        <div className="flex flex-wrap gap-1 border-b border-ink-700 px-3 py-2">
          {alarms.map((alarm) => (
            <span key={alarm} className="rounded bg-rose-900/60 px-1.5 py-0.5 font-mono text-2xs text-rose-200">
              {alarm}
            </span>
          ))}
        </div>
      ) : null}
      <ol className="min-h-0 flex-1 overflow-auto px-2 py-1 font-mono text-2xs">
        {visible.length === 0 ? (
          <li className="px-1 py-6 text-center text-slate-500">No events yet. Run a scenario.</li>
        ) : (
          visible.map((event, index) => (
            <li
              key={`${event.timestamp_ms}-${event.event_type}-${index}`}
              className={`flex gap-2 border-b border-ink-800 py-1 ${
                event.event_type === "ALARM_RAISED" ? "text-rose-300" : "text-slate-300"
              }`}
            >
              <span className="w-14 shrink-0 text-slate-500">{event.timestamp_ms.toString().padStart(5, " ")}</span>
              <span className="w-[11rem] shrink-0 text-slate-200">{event.event_type}</span>
              <span className="truncate text-slate-400">
                {formatValue(event.value)}
                {event.detail ? ` · ${event.detail}` : ""}
              </span>
            </li>
          ))
        )}
      </ol>
    </section>
  );
}

function formatValue(value: JourneyEvent["value"]): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}
