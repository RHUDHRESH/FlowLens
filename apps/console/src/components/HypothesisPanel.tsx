import type { IncidentEnvelope } from "../types";
import { hypothesisLabel } from "../types";

interface Props {
  envelope: IncidentEnvelope | null;
}

export function HypothesisPanel({ envelope }: Props) {
  if (!envelope) {
    return (
      <section className="panel flex items-center justify-center p-6 text-center text-xs text-slate-500">
        Run a scenario. Ranked hypotheses, contradictions, abstention and the next
        permitted test appear here from the evidence envelope — never from a chatbot.
      </section>
    );
  }

  const { abstention, top_hypotheses: hyps, next_test: next } = envelope;

  return (
    <section className="panel flex min-h-0 flex-col overflow-hidden">
      <header className="border-b border-ink-600 px-3 py-2 text-2xs uppercase tracking-[0.14em] text-slate-500">
        Hypotheses · evidence · next test
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        <div className="rounded border border-ink-600 bg-ink-800 p-2 text-xs text-slate-200">
          <div className="mb-1 font-semibold text-white">{envelope.headline}</div>
          <p className="text-slate-300">{abstention.reason}</p>
          <div className="mt-1 font-mono text-2xs text-slate-500">rule {abstention.triggered_rule}</div>
          {abstention.novelty ? (
            <div className="mt-1 text-2xs text-slate-400">
              novelty {abstention.novelty.score.toFixed(2)} / {abstention.novelty.threshold.toFixed(2)}
              {abstention.novelty.is_novel ? " · outside healthy support" : " · inside healthy support"}
            </div>
          ) : null}
          {abstention.conformal ? (
            <div className="mt-1 text-2xs text-slate-400">
              {(1 - abstention.conformal.alpha) * 100}% set ({abstention.conformal.set_size}):{" "}
              {abstention.conformal.label_set.slice(0, 4).join(", ")}
            </div>
          ) : null}
        </div>

        {hyps.map((h, index) => (
          <article
            key={`${hypothesisLabel(h)}-${index}`}
            className={`rounded border p-2 ${index === 0 ? "border-wire/60 bg-ink-800" : "border-ink-600"}`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-xs font-semibold text-white">
                {index + 1}. {hypothesisLabel(h)}
              </h3>
              <span className="font-mono text-2xs text-slate-400">{(h.probability * 100).toFixed(1)}%</span>
            </div>
            <p className="mt-1 text-2xs text-slate-400">{h.rationale}</p>
            {h.support.length > 0 ? (
              <List title="Support" items={h.support.map((i) => i.statement)} tone="good" />
            ) : null}
            {h.contradictions.length > 0 ? (
              <List title="Contradictions" items={h.contradictions.map((i) => i.statement)} tone="bad" />
            ) : null}
          </article>
        ))}

        {next ? (
          <article className="rounded border border-emerald-800/80 bg-emerald-950/30 p-2">
            <div className="text-2xs uppercase tracking-[0.14em] text-emerald-400">Next permitted test</div>
            <h3 className="mt-1 text-xs font-semibold text-white">{next.name}</h3>
            <p className="mt-1 text-2xs text-slate-300">{next.reason}</p>
            <div className="mt-1 font-mono text-2xs text-slate-500">
              {next.safety_class} · {next.duration_minutes.toFixed(0)} min · ΔH{" "}
              {next.expected_entropy_reduction_bits.toFixed(2)} bit / {next.prior_entropy_bits.toFixed(2)}
            </div>
            <table className="mt-2 w-full text-2xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="text-left font-medium">If observed</th>
                  <th className="text-right font-medium">p</th>
                  <th className="text-right font-medium">Would lead</th>
                </tr>
              </thead>
              <tbody>
                {next.outcome_effects.map((o) => (
                  <tr key={o.outcome_id} className="border-t border-ink-700">
                    <td className="py-1 pr-2 text-slate-300">{o.description}</td>
                    <td className="py-1 text-right font-mono text-slate-400">
                      {(o.probability * 100).toFixed(0)}%
                    </td>
                    <td className="py-1 text-right text-slate-300">
                      {o.would_lead_to.replaceAll("_", " ")} {(o.would_reach * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-2xs text-slate-500">
              Selected from the reviewed whitelist. FlowLens cannot invent a procedure or
              recommend an actuating test.
            </p>
          </article>
        ) : (
          <p className="text-2xs text-slate-500">No additional permitted test is required on this ranking.</p>
        )}

        <details className="text-2xs text-slate-500">
          <summary className="cursor-pointer text-slate-400">Evidence envelope versions</summary>
          <pre className="mt-1 overflow-auto whitespace-pre-wrap font-mono">
            {JSON.stringify(
              {
                versions: envelope.versions,
                raw_trace_hash: envelope.raw_trace_hash,
                config_hash: envelope.config_hash,
                incident_id: envelope.incident_id,
              },
              null,
              2,
            )}
          </pre>
        </details>
      </div>
    </section>
  );
}

function List({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "bad";
}) {
  return (
    <div className="mt-2">
      <div className={`text-2xs font-semibold ${tone === "good" ? "text-emerald-400" : "text-rose-400"}`}>
        {title}
      </div>
      <ul className="mt-0.5 space-y-0.5">
        {items.slice(0, 4).map((item) => (
          <li key={item} className="text-2xs leading-snug text-slate-300">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
