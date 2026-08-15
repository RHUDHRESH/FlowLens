import type { DemoButton } from "../types";

interface Props {
  buttons: DemoButton[];
  activeId: string | null;
  busy: boolean;
  canStep: boolean;
  canExport: boolean;
  onSelect: (scenarioId: string) => void;
  onRun: () => void;
  onPause: () => void;
  onStep: () => void;
  onReset: () => void;
  onExport: () => void;
}

export function Controls({
  buttons,
  activeId,
  busy,
  canStep,
  canExport,
  onSelect,
  onRun,
  onPause,
  onStep,
  onReset,
  onExport,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 bg-ink-900 px-4 py-2">
      <div className="flex flex-wrap gap-1">
        {buttons.map((button) => {
          const on = button.scenario_id === activeId;
          return (
            <button
              key={button.scenario_id}
              type="button"
              disabled={busy}
              onClick={() => onSelect(button.scenario_id)}
              className={`rounded px-2.5 py-1 text-2xs font-medium uppercase tracking-wide ${
                on
                  ? "bg-wire/20 text-wire ring-1 ring-wire"
                  : "bg-ink-750 text-slate-300 hover:bg-ink-700"
              } disabled:opacity-50`}
            >
              {button.label}
            </button>
          );
        })}
      </div>
      <div className="ml-auto flex gap-1">
        <Action onClick={onRun} disabled={busy || !activeId}>
          Run
        </Action>
        <Action onClick={onPause} disabled={!busy}>
          Pause
        </Action>
        <Action onClick={onStep} disabled={!canStep}>
          Step
        </Action>
        <Action onClick={onReset} disabled={!activeId}>
          Reset
        </Action>
        <Action onClick={onExport} disabled={!canExport} accent>
          Export report
        </Action>
      </div>
    </div>
  );
}

function Action({
  children,
  onClick,
  disabled,
  accent,
}: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  accent?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-2.5 py-1 text-2xs font-semibold uppercase tracking-wide disabled:opacity-40 ${
        accent ? "bg-wire text-ink-950" : "bg-ink-750 text-slate-200 hover:bg-ink-700"
      }`}
    >
      {children}
    </button>
  );
}
