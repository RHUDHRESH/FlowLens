import type {
  CreateRunResponse,
  DemoButton,
  IncidentEnvelope,
  ScenarioInfo,
} from "./types";

const API = "/api/v1";

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchHealth(): Promise<{
  status: string;
  versions: Record<string, string>;
  read_only: boolean;
}> {
  return parse(await fetch("/health"));
}

export async function fetchScenarios(): Promise<{
  demo_buttons: DemoButton[];
  scenarios: ScenarioInfo[];
}> {
  return parse(await fetch(`${API}/scenarios`));
}

export async function createRun(
  scenarioId: string,
  autoplay = false,
): Promise<CreateRunResponse> {
  return parse(
    await fetch(`${API}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId, seed: 20260915, autoplay }),
    }),
  );
}

export async function stepRun(runId: string, deltaMs = 500): Promise<{ cursor_ms: number; complete: boolean }> {
  return parse(
    await fetch(`${API}/runs/${runId}/step`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delta_ms: deltaMs }),
    }),
  );
}

export async function pauseRun(runId: string): Promise<void> {
  await parse(await fetch(`${API}/runs/${runId}/pause`, { method: "POST" }));
}

export async function resumeRun(runId: string): Promise<void> {
  await parse(await fetch(`${API}/runs/${runId}/resume`, { method: "POST" }));
}

export async function resetRun(runId: string): Promise<void> {
  await parse(await fetch(`${API}/runs/${runId}/reset`, { method: "POST" }));
}

export async function fetchEvents(
  runId: string,
  untilMs?: number,
): Promise<{ events: import("./types").JourneyEvent[]; frames: import("./types").SignalFrame[] }> {
  const qs = untilMs === undefined ? "" : `?until_ms=${untilMs}`;
  return parse(await fetch(`${API}/runs/${runId}/events${qs}`));
}

export async function fetchDiagnosis(runId: string, refresh = false): Promise<IncidentEnvelope> {
  const qs = refresh ? "?refresh=true" : "";
  return parse(await fetch(`${API}/runs/${runId}/diagnosis${qs}`));
}

export function reportUrl(incidentId: string): string {
  return `${API}/incidents/${incidentId}/report`;
}

export function openStream(runId: string): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${window.location.host}${API}/runs/${runId}/stream`);
}
