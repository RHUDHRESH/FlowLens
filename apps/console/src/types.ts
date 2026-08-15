export interface DemoButton {
  label: string;
  scenario_id: string;
}

export interface ScenarioInfo {
  scenario_id: string;
  title: string;
  family: string;
  description: string;
  demo_button?: string | null;
}

export interface JourneyEvent {
  timestamp_ms: number;
  event_type: string;
  value: boolean | number | string | null;
  detail?: string | null;
  quality: number;
}

export interface SignalFrame {
  timestamp_ms: number;
  signals: Record<string, number>;
  quality: Record<string, number>;
}

export interface JourneySegment {
  phase: string;
  start_ms: number;
  end_ms: number | null;
  dwell_ms?: number | null;
  guard_ms?: number | null;
  timed_out: boolean;
  expected_next: string[];
  entry_evidence: string[];
}

export interface FirstDeviation {
  phase: string;
  type: string;
  timestamp_ms: number;
  expected_next?: string | null;
  observed_delay_ms?: number | null;
  statement: string;
  affected_domains: string[];
  confidence: number;
}

export interface EvidenceItem {
  key: string;
  statement: string;
  value?: number | null;
  weight: number;
  direction: "support" | "contradiction" | "neutral";
  phase?: string | null;
}

export interface Hypothesis {
  faults: string[];
  probability: number;
  log_score: number;
  support: EvidenceItem[];
  contradictions: EvidenceItem[];
  causal_path: string[];
  first_deviation_fit: number;
  downstream_coverage: number;
  onset_phase?: string | null;
  rationale: string;
  label?: string;
}

export interface ChannelQuality {
  channel: string;
  present: boolean;
  mean_quality: number;
  coverage: number;
  defects: string[];
  usable: boolean;
}

export interface NextTest {
  test_id: string;
  name: string;
  reason: string;
  safety_class: string;
  expected_entropy_reduction_bits: number;
  prior_entropy_bits: number;
  expected_posterior_entropy_bits: number;
  utility: number;
  duration_minutes: number;
  outcome_effects: Array<{
    outcome_id: string;
    description: string;
    probability: number;
    would_lead_to: string;
    would_reach: number;
  }>;
  alternatives: Array<{
    test_id: string;
    name: string;
    expected_bits: number;
    utility: number;
    duration_minutes: number;
    safety_class: string;
  }>;
}

export interface NoveltyReport {
  score: number;
  threshold: number;
  is_novel: boolean;
  worst_features: string[];
}

export interface ConformalReport {
  alpha: number;
  nonconformity_threshold: number;
  label_set: string[];
  set_size: number;
}

export interface AbstentionReport {
  decision: string;
  reason: string;
  triggered_rule: string;
  margin?: number | null;
  novelty?: NoveltyReport | null;
  conformal?: ConformalReport | null;
  blocking_channels: string[];
}

export interface IncidentEnvelope {
  incident_id: string;
  asset_id: string;
  journey_id: string;
  run_id?: string | null;
  scenario_id?: string | null;
  created_at: string;
  decision: string;
  abstention: AbstentionReport;
  headline: string;
  journey: JourneySegment[];
  terminal_phase?: string | null;
  first_deviation?: FirstDeviation | null;
  deviations: FirstDeviation[];
  channel_quality: ChannelQuality[];
  features: Record<string, number>;
  top_hypotheses: Hypothesis[];
  next_test?: NextTest | null;
  alarms: string[];
  latency_ms: number;
  versions: Record<string, string>;
  raw_trace_hash: string;
  config_hash: string;
  safety_notice: string;
}

export interface CreateRunResponse {
  run_id: string;
  scenario_id: string;
  asset_id: string;
  journey_id: string;
  seed: number;
  duration_ms: number;
  frame_count: number;
  event_count: number;
  config_hash: string;
  stream_url: string;
}

export type StreamMessage =
  | { type: "start"; run_id: string; scenario_id: string; duration_ms: number }
  | {
      type: "batch";
      from_ms: number;
      to_ms: number;
      events: JourneyEvent[];
      frames: SignalFrame[];
    }
  | { type: "diagnosis"; envelope: IncidentEnvelope }
  | { type: "complete"; run_id: string }
  | { type: "error"; detail: string };

export const SIGNAL_KEYS = [
  { key: "dc_bus_v", label: "DC bus V", unit: "V" },
  { key: "motor_current_a", label: "Motor A", unit: "A" },
  { key: "speed_mps", label: "Speed", unit: "m/s" },
  { key: "brake_current_a", label: "Brake A", unit: "A" },
  { key: "door_current_a", label: "Door A", unit: "A" },
  { key: "drive_temp_c", label: "Drive °C", unit: "°C" },
  { key: "vibration_rms", label: "Vib RMS", unit: "" },
] as const;

export const PHASE_ORDER = [
  "IDLE",
  "CALL_ACCEPTED",
  "DOOR_CLOSING",
  "LOCK_PROVED",
  "SAFETY_CHAIN_PROVED",
  "START_PERMIT",
  "BRAKE_RELEASE",
  "TORQUE_BUILD",
  "ACCELERATION",
  "CRUISE",
  "DECELERATION",
  "LEVELING",
  "BRAKE_SET",
  "DOOR_OPENING",
  "DOOR_OPEN",
  "INCIDENT_STOP",
  "MAINTENANCE",
];

export function hypothesisLabel(h: Hypothesis): string {
  if (h.label) return h.label.replaceAll("_", " ");
  if (!h.faults.length) return "healthy";
  return h.faults.join(" + ").replaceAll("_", " ");
}
