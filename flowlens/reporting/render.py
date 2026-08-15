"""Render an incident envelope to a self-contained technician report.

The report is generated from the *same* envelope the console displays. There is
no separate report query, no recomputation and no rounding done only for print,
so a printed report and a screen cannot disagree.

Output is a single HTML file with no external references, which prints to PDF
from any browser. If ``weasyprint`` is installed, :func:`render_pdf` produces the
PDF directly; it is optional because it pulls in native libraries that would
otherwise make a clean-machine setup fragile.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, select_autoescape

from flowlens.contracts.schemas import IncidentEnvelope

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FlowLens incident {{ e.incident_id }}</title>
<style>
  :root {
    --ink: #14181f; --muted: #5b6472; --line: #d8dde5; --bg: #ffffff;
    --panel: #f6f8fa; --accent: #1d4ed8; --warn: #b45309; --bad: #b91c1c;
    --good: #15803d;
  }
  * { box-sizing: border-box; }
  body { font: 13px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif;
         color: var(--ink); background: var(--bg); margin: 0; padding: 32px; }
  .sheet { max-width: 940px; margin: 0 auto; }
  header { border-bottom: 3px solid var(--ink); padding-bottom: 12px; margin-bottom: 18px; }
  h1 { font-size: 20px; margin: 0 0 4px; letter-spacing: -0.01em; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .09em;
       color: var(--muted); margin: 26px 0 8px; }
  .sub { color: var(--muted); font-size: 12px; }
  .decision { display: inline-block; padding: 5px 11px; border-radius: 4px;
              font-weight: 700; letter-spacing: .04em; font-size: 12px; color: #fff; }
  .d-HEALTHY { background: var(--good); }
  .d-KNOWN_FAULT { background: var(--accent); }
  .d-UNKNOWN_FAULT, .d-HUMAN_REVIEW, .d-INSUFFICIENT_DATA, .d-OUT_OF_SCOPE { background: var(--warn); }
  .d-SENSOR_CHECK { background: #7c3aed; }
  .headline { font-size: 16px; font-weight: 600; margin: 10px 0 6px; }
  .panel { background: var(--panel); border: 1px solid var(--line);
           border-radius: 6px; padding: 12px 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line);
           vertical-align: top; }
  th { color: var(--muted); font-weight: 600; text-transform: uppercase;
       font-size: 10px; letter-spacing: .07em; }
  .hyp { border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px;
         margin-bottom: 10px; page-break-inside: avoid; }
  .hyp.lead { border-color: var(--accent); border-width: 2px; }
  .hyp h3 { margin: 0 0 6px; font-size: 14px; }
  .prob { float: right; font-variant-numeric: tabular-nums; color: var(--muted); }
  ul { margin: 4px 0 0; padding-left: 18px; }
  li { margin: 2px 0; }
  .support li { color: var(--good); }
  .contra li { color: var(--bad); }
  .support li span, .contra li span { color: var(--ink); }
  .chain { counter-reset: step; margin: 6px 0 0; padding: 0; list-style: none; }
  .chain li { counter-increment: step; padding-left: 26px; position: relative; margin: 4px 0; }
  .chain li::before { content: counter(step); position: absolute; left: 0; top: 1px;
      width: 18px; height: 18px; border-radius: 50%; background: var(--ink); color: #fff;
      font-size: 10px; text-align: center; line-height: 18px; }
  .notice { border-left: 4px solid var(--bad); background: #fef2f2; padding: 10px 14px;
            margin-top: 26px; font-size: 12px; }
  .mono { font-family: "Cascadia Mono", Consolas, monospace; font-size: 11px; }
  footer { margin-top: 26px; border-top: 1px solid var(--line); padding-top: 10px;
           color: var(--muted); font-size: 11px; }
  @media print { body { padding: 0; } .hyp, .panel { page-break-inside: avoid; } }
</style>
</head>
<body><div class="sheet">

<header>
  <h1>FlowLens incident report</h1>
  <div class="sub">
    Incident <span class="mono">{{ e.incident_id }}</span> &middot;
    asset <span class="mono">{{ e.asset_id }}</span> &middot;
    journey <span class="mono">{{ e.journey_id }}</span> &middot;
    generated {{ e.created_at }}
  </div>
</header>

<span class="decision d-{{ e.decision.value }}">{{ e.decision.value.replace('_', ' ') }}</span>
<div class="headline">{{ e.headline }}</div>
<div class="panel">{{ e.abstention.reason }}
  <div class="sub" style="margin-top:6px">Decision rule: <span class="mono">{{ e.abstention.triggered_rule }}</span></div>
</div>

{% if e.first_deviation %}
<h2>First causal deviation</h2>
<div class="panel">
  <strong>{{ e.first_deviation.phase.value }} &middot;
  {{ e.first_deviation.type.value.replace('_', ' ').lower() }}</strong>
  at {{ e.first_deviation.timestamp_ms }} ms
  <p style="margin:8px 0 0">{{ e.first_deviation.statement }}</p>
  {% if e.first_deviation.affected_domains %}
  <div class="sub" style="margin-top:6px">
    Candidate domains: {{ e.first_deviation.affected_domains | join(', ') }}
  </div>
  {% endif %}
</div>
{% endif %}

<h2>Ranked explanations</h2>
{% for h in e.top_hypotheses %}
<div class="hyp {% if loop.first %}lead{% endif %}">
  <span class="prob">{{ '%.1f' % (h.probability * 100) }}%</span>
  <h3>{{ h.label.replace('_', ' ') }}</h3>
  <div class="sub">{{ h.rationale }}</div>
  {% if h.support %}
  <div class="support"><strong>Supporting evidence</strong>
    <ul>{% for i in h.support %}<li><span>{{ i.statement }}</span></li>{% endfor %}</ul>
  </div>{% endif %}
  {% if h.contradictions %}
  <div class="contra" style="margin-top:6px"><strong>Contradicting evidence</strong>
    <ul>{% for i in h.contradictions %}<li><span>{{ i.statement }}</span></li>{% endfor %}</ul>
  </div>{% endif %}
  {% if loop.first and h.causal_path %}
  <div style="margin-top:8px"><strong>Proposed causal chain</strong>
    <ol class="chain">{% for step in h.causal_path %}<li>{{ step }}</li>{% endfor %}</ol>
  </div>{% endif %}
</div>
{% endfor %}

{% if e.next_test %}
<h2>Recommended next diagnostic step</h2>
<div class="panel">
  <strong>{{ e.next_test.name }}</strong>
  <span class="sub">&mdash; {{ e.next_test.safety_class.value.replace('_', ' ').lower() }},
  about {{ '%.0f' % e.next_test.duration_minutes }} minutes</span>
  <p style="margin:8px 0">{{ e.next_test.reason }}</p>
  <table>
    <tr><th>If the result is</th><th>Probability</th><th>Leading explanation becomes</th></tr>
    {% for o in e.next_test.outcome_effects %}
    <tr><td>{{ o.description }}</td>
        <td>{{ '%.0f' % (o.probability * 100) }}%</td>
        <td>{{ o.would_lead_to.replace('_', ' ') }} at {{ '%.0f' % (o.would_reach * 100) }}%</td></tr>
    {% endfor %}
  </table>
  <div class="sub" style="margin-top:8px">
    Selected from the reviewed permitted-test whitelist. FlowLens cannot generate a
    procedure and never recommends an actuating test.
  </div>
</div>
{% endif %}

<h2>Reconstructed journey</h2>
<table>
  <tr><th>Phase</th><th>Entered</th><th>Dwell</th><th>Guard</th><th>Entry evidence</th></tr>
  {% for s in e.journey %}
  <tr>
    <td><strong>{{ s.phase.value }}</strong></td>
    <td class="mono">{{ s.start_ms }} ms</td>
    <td class="mono">{{ s.dwell_ms if s.dwell_ms is not none else '-' }} ms{% if s.timed_out %}
        <span style="color:var(--bad)"> over guard</span>{% endif %}</td>
    <td class="mono">{{ s.guard_ms if s.guard_ms is not none else '-' }}</td>
    <td class="sub">{{ s.entry_evidence | join('; ') }}</td>
  </tr>
  {% endfor %}
</table>

{% if degraded %}
<h2>Channel integrity</h2>
<table>
  <tr><th>Channel</th><th>Coverage</th><th>Quality</th><th>Observed defects</th></tr>
  {% for c in degraded %}
  <tr><td class="mono">{{ c.channel }}</td>
      <td>{{ '%.0f' % (c.coverage * 100) }}%</td>
      <td>{{ '%.2f' % c.mean_quality }}</td>
      <td>{{ c.defects | join(', ') }}</td></tr>
  {% endfor %}
</table>
{% endif %}

<h2>Uncertainty</h2>
<div class="panel">
  {% if e.abstention.novelty %}
  Novelty {{ '%.2f' % e.abstention.novelty.score }} against a healthy threshold of
  {{ '%.2f' % e.abstention.novelty.threshold }}
  ({{ 'outside' if e.abstention.novelty.is_novel else 'inside' }} the calibrated healthy range).
  {% if e.abstention.novelty.worst_features %}
  <div class="sub" style="margin-top:4px">Most abnormal:
    {{ e.abstention.novelty.worst_features | join(', ') }}</div>
  {% endif %}
  {% endif %}
  {% if e.abstention.conformal %}
  <div style="margin-top:8px">
    Calibrated prediction set at
    {{ '%.0f' % ((1 - e.abstention.conformal.alpha) * 100) }}% coverage contains
    {{ e.abstention.conformal.set_size }} explanation(s):
    <span class="mono">{{ e.abstention.conformal.label_set[:6] | join(', ') }}</span>
  </div>
  {% endif %}
</div>

<div class="notice">
  <strong>Safety notice.</strong> {{ e.safety_notice }}
  Every recommendation is advisory and requires a trained technician's judgement and
  the site's approved procedures.
</div>

<footer>
  Alarms observed: {{ e.alarms | join(', ') if e.alarms else 'none' }}<br>
  Inference latency {{ '%.1f' % e.latency_ms }} ms &middot;
  trace <span class="mono">{{ e.raw_trace_hash[:26] }}</span> &middot;
  config <span class="mono">{{ e.config_hash[:26] }}</span><br>
  Versions:
  {% for k, v in e.versions.items() %}{{ k }}={{ v }}{% if not loop.last %} &middot; {% endif %}{% endfor %}
  <br><br>
  Results in this report were produced by a deterministic simulator, not by a field
  installation. They are not evidence of field accuracy and carry no safety certification.
</footer>

</div></body></html>
"""


def _environment() -> Environment:
    env = Environment(autoescape=select_autoescape(["html"]))
    return env


def render_report_html(envelope: IncidentEnvelope) -> str:
    """Render the envelope to a self-contained HTML document."""
    template = _environment().from_string(_TEMPLATE)
    degraded = [c for c in envelope.channel_quality if c.defects]
    return template.render(e=envelope, degraded=degraded)


def render_report(envelope: IncidentEnvelope, out_path: Path | str) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report_html(envelope), encoding="utf-8")
    return path


def render_pdf(envelope: IncidentEnvelope, out_path: Path | str) -> Path:
    """Render straight to PDF if weasyprint is available.

    Optional on purpose: weasyprint needs native libraries, and requiring them
    would make a clean-machine ``docker compose up`` more fragile than the demo
    can afford. The HTML report prints to PDF from any browser.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "weasyprint is not installed. Render the HTML report and print it to PDF "
            "from a browser, or install the optional 'pdf' extra."
        ) from exc

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=render_report_html(envelope)).write_pdf(str(path))
    return path
