import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { FirstDeviation, Hypothesis } from "../types";

const NODES: Array<{ id: string; label: string; x: number; y: number; phases: string[]; faults: string[] }> = [
  { id: "door", label: "Door operator", x: 0, y: 40, phases: ["DOOR_CLOSING", "DOOR_OPENING"], faults: ["door_obstruction", "door_motor_overload"] },
  { id: "lock", label: "Door lock", x: 180, y: 40, phases: ["LOCK_PROVED"], faults: ["door_lock_bounce", "door_lock_proof_absent"] },
  { id: "safety", label: "Safety chain", x: 360, y: 40, phases: ["SAFETY_CHAIN_PROVED"], faults: ["safety_chain_intermittent"] },
  { id: "permit", label: "Start permit", x: 540, y: 40, phases: ["START_PERMIT"], faults: ["start_permit_missing", "contactor_delay"] },
  { id: "brake", label: "Brake", x: 180, y: 170, phases: ["BRAKE_RELEASE", "BRAKE_SET"], faults: ["brake_drag", "brake_release_failure"] },
  { id: "drive", label: "Drive / torque", x: 360, y: 170, phases: ["TORQUE_BUILD", "ACCELERATION"], faults: ["drive_overcurrent", "drive_cooling_degradation", "dc_bus_undervoltage", "supply_sag"] },
  { id: "encoder", label: "Encoder", x: 540, y: 170, phases: ["ACCELERATION", "CRUISE"], faults: ["encoder_dropout", "encoder_drift", "speed_mismatch"] },
  { id: "motion", label: "Car motion", x: 720, y: 100, phases: ["CRUISE", "DECELERATION", "LEVELING"], faults: ["mechanical_resistance"] },
  { id: "sensor", label: "Sensors / data", x: 0, y: 170, phases: [], faults: ["sensor_fault", "comms_corruption", "door_position_sensor_fault"] },
];

const LINKS: Array<[string, string]> = [
  ["door", "lock"],
  ["lock", "safety"],
  ["safety", "permit"],
  ["permit", "drive"],
  ["brake", "motion"],
  ["drive", "motion"],
  ["encoder", "drive"],
  ["sensor", "encoder"],
  ["sensor", "drive"],
];

interface Props {
  leading: Hypothesis | null;
  deviation: FirstDeviation | null | undefined;
}

export function CausalGraph({ leading, deviation }: Props) {
  const activeFaults = new Set(leading?.faults ?? []);
  const activeNodes = new Set(
    NODES.filter(
      (n) =>
        n.faults.some((f) => activeFaults.has(f)) ||
        (deviation && n.phases.includes(deviation.phase)),
    ).map((n) => n.id),
  );

  const nodes: Node[] = NODES.map((n) => {
    const on = activeNodes.has(n.id);
    const isDev = Boolean(deviation && n.phases.includes(deviation.phase));
    return {
      id: n.id,
      position: { x: n.x, y: n.y },
      data: { label: n.label },
      style: {
        borderRadius: 6,
        borderWidth: isDev ? 2 : 1,
        borderColor: isDev ? "#fbbf24" : on ? "#22c3d6" : "#33455c",
        background: isDev ? "#3a2a12" : on ? "#12343a" : "#101822",
        color: on || isDev ? "#e8f4f7" : "#7b8796",
        fontSize: 11,
        width: 132,
        padding: "6px 8px",
      },
    };
  });

  const edges: Edge[] = LINKS.map(([source, target]) => {
    const on = activeNodes.has(source) && activeNodes.has(target);
    return {
      id: `${source}-${target}`,
      source,
      target,
      animated: on,
      style: { stroke: on ? "#22c3d6" : "#243346", strokeWidth: on ? 2 : 1 },
      markerEnd: { type: MarkerType.ArrowClosed, color: on ? "#22c3d6" : "#243346" },
    };
  });

  return (
    <section className="panel relative min-h-[280px] overflow-hidden">
      <header className="absolute left-3 top-2 z-10 text-2xs uppercase tracking-[0.14em] text-slate-500">
        Causal path
      </header>
      <div className="absolute inset-0 pt-7">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll={false}
      >
        <Background color="#1b2836" gap={18} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      </div>
      {leading?.causal_path?.length ? (
        <ol className="pointer-events-none absolute bottom-2 left-3 right-3 space-y-0.5 text-2xs text-slate-300">
          {leading.causal_path.slice(0, 4).map((step, i) => (
            <li key={step}>
              <span className="mr-1 text-wire">{i + 1}.</span>
              {step}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
