"""FlowLens read-only diagnostic API.

Every endpoint is read-only with respect to the elevator. Nothing here can
command motion, reset an alarm, release a brake, bypass a safety circuit or
authorize return to service - and there is no code path that could, because the
API only ever reads recordings and returns analysis.

``POST`` endpoints exist for driving *playback* of a recording and for recording
a technician's observed test result. Neither touches an installation.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from flowlens.contracts.enums import MaintenanceState
from flowlens.contracts.schemas import (
    IncidentEnvelope,
    RunRecord,
    TestOutcomeReport,
)
from flowlens.diagnosis.engine import get_engine
from flowlens.simulator.runner import simulate_scenario
from flowlens.simulator.scenarios import DEMO_BUTTONS, get_scenario, list_scenarios
from flowlens.store import Store
from flowlens.test_planner.planner import PlannerError, apply_test_result, plan_next_test
from flowlens.version import component_versions

API_PREFIX = "/api/v1"

#: Playback speed for the streaming endpoint. The console renders a journey in a
#: few seconds rather than the ~14 s a real one takes.
PLAYBACK_SPEED = 8.0
STREAM_BATCH_MS = 200


@dataclass
class ActiveRun:
    """In-memory playback state for one loaded recording."""

    record: RunRecord
    cursor_ms: int = 0
    paused: bool = False
    envelope: IncidentEnvelope | None = None
    test_results: list[TestOutcomeReport] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.record.frames[-1].timestamp_ms if self.record.frames else 0

    @property
    def complete(self) -> bool:
        return self.cursor_ms >= self.duration_ms

    def slice_to(self, until_ms: int) -> dict[str, Any]:
        return {
            "events": [
                e.model_dump(mode="json")
                for e in self.record.events
                if e.timestamp_ms <= until_ms
            ],
            "frames": [
                f.model_dump(mode="json")
                for f in self.record.frames
                if f.timestamp_ms <= until_ms
            ],
        }


RUNS: dict[str, ActiveRun] = {}
STORE = Store()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the fitted models so the first diagnosis is not slower than the rest.
    get_engine()
    yield
    RUNS.clear()


app = FastAPI(
    title="FlowLens RCA Lab",
    version=component_versions()["flowlens"],
    description=(
        "Read-only elevator fault isolation and root cause analysis. "
        "FlowLens is advisory: it cannot reset faults, command motion, release a brake, "
        "bypass a safety circuit, or authorize return to service."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONSOLE_DIST = Path(__file__).resolve().parent.parent / "console" / "dist"


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class CreateRunRequest(BaseModel):
    scenario_id: str
    seed: int = 20260915
    maintenance_state: MaintenanceState = MaintenanceState.IN_SERVICE
    autoplay: bool = Field(default=False, description="Advance the cursor to the end immediately")


class StepRequest(BaseModel):
    delta_ms: int = Field(default=500, ge=20, le=60_000)


# --------------------------------------------------------------------------- #
# Health and metadata
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict[str, Any]:
    engine = get_engine()
    return {
        "status": "ok",
        "versions": component_versions(),
        "models": {
            "evidence": engine.evidence_engine.source,
            "novelty": engine.novelty_model.source,
            "conformal": engine.conformal_source,
        },
        "active_runs": len(RUNS),
        "read_only": True,
    }


@app.get(f"{API_PREFIX}/scenarios")
def scenarios() -> dict[str, Any]:
    buttons = {scenario_id: label for label, scenario_id in DEMO_BUTTONS}
    return {
        "demo_buttons": [
            {"label": label, "scenario_id": scenario_id} for label, scenario_id in DEMO_BUTTONS
        ],
        "scenarios": [
            {
                **spec.model_dump(mode="json"),
                "demo_button": buttons.get(spec.scenario_id),
            }
            for spec in list_scenarios()
        ],
    }


@app.get(f"{API_PREFIX}/permitted-tests")
def permitted_test_whitelist() -> dict[str, Any]:
    from flowlens.config import permitted_tests

    whitelist = permitted_tests()
    return {
        "version": whitelist.version,
        "notice": (
            "The planner may only ever select from this list. It cannot synthesize a "
            "procedure and cannot recommend an actuating test."
        ),
        "tests": [test.model_dump(mode="json") for test in whitelist.tests],
    }


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


@app.post(f"{API_PREFIX}/runs", status_code=201)
def create_run(request: CreateRunRequest) -> dict[str, Any]:
    try:
        get_scenario(request.scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    record = simulate_scenario(request.scenario_id, seed=request.seed)
    record.maintenance_state = request.maintenance_state
    STORE.save_run(record)

    active = ActiveRun(record=record)
    if request.autoplay:
        active.cursor_ms = active.duration_ms
    RUNS[record.run_id] = active

    return {
        "run_id": record.run_id,
        "scenario_id": record.scenario_id,
        "asset_id": record.asset_id,
        "journey_id": record.journey_id,
        "seed": record.seed,
        "duration_ms": active.duration_ms,
        "frame_count": len(record.frames),
        "event_count": len(record.events),
        "config_hash": record.config_hash,
        "stream_url": f"{API_PREFIX}/runs/{record.run_id}/stream",
    }


def _require(run_id: str) -> ActiveRun:
    active = RUNS.get(run_id)
    if active is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} is not loaded")
    return active


@app.get(f"{API_PREFIX}/runs/{{run_id}}")
def get_run(run_id: str) -> dict[str, Any]:
    active = _require(run_id)
    return {
        "run_id": run_id,
        "scenario_id": active.record.scenario_id,
        "cursor_ms": active.cursor_ms,
        "duration_ms": active.duration_ms,
        "paused": active.paused,
        "complete": active.complete,
        "test_results": [r.model_dump(mode="json") for r in active.test_results],
    }


@app.post(f"{API_PREFIX}/runs/{{run_id}}/step")
def step_run(run_id: str, request: StepRequest) -> dict[str, Any]:
    active = _require(run_id)
    active.cursor_ms = min(active.cursor_ms + request.delta_ms, active.duration_ms)
    return {"run_id": run_id, "cursor_ms": active.cursor_ms, "complete": active.complete}


@app.post(f"{API_PREFIX}/runs/{{run_id}}/pause")
def pause_run(run_id: str) -> dict[str, Any]:
    active = _require(run_id)
    active.paused = True
    return {"run_id": run_id, "paused": True, "cursor_ms": active.cursor_ms}


@app.post(f"{API_PREFIX}/runs/{{run_id}}/resume")
def resume_run(run_id: str) -> dict[str, Any]:
    active = _require(run_id)
    active.paused = False
    return {"run_id": run_id, "paused": False, "cursor_ms": active.cursor_ms}


@app.post(f"{API_PREFIX}/runs/{{run_id}}/reset")
def reset_run(run_id: str) -> dict[str, Any]:
    """Rewind playback. This resets the *viewer*, never an elevator."""
    active = _require(run_id)
    active.cursor_ms = 0
    active.paused = False
    active.envelope = None
    active.test_results.clear()
    return {"run_id": run_id, "cursor_ms": 0, "paused": False}


@app.get(f"{API_PREFIX}/runs/{{run_id}}/events")
def get_events(
    run_id: str, until_ms: int | None = Query(default=None, ge=0)
) -> dict[str, Any]:
    active = _require(run_id)
    cutoff = active.duration_ms if until_ms is None else until_ms
    payload = active.slice_to(cutoff)
    return {"run_id": run_id, "until_ms": cutoff, **payload}


@app.get(f"{API_PREFIX}/runs/{{run_id}}/diagnosis")
def get_diagnosis(run_id: str, refresh: bool = False) -> IncidentEnvelope:
    active = _require(run_id)
    if active.envelope is None or refresh:
        record = active.record
        envelope = get_engine().diagnose(
            record.observable(),
            incident_id=f"incident_{record.run_id}",
            run_id=record.run_id,
            scenario_id=record.scenario_id,
        ).envelope
        active.envelope = envelope
        STORE.save_incident(envelope)
    return active.envelope


@app.post(f"{API_PREFIX}/runs/{{run_id}}/test-results")
def submit_test_result(run_id: str, result: TestOutcomeReport) -> dict[str, Any]:
    """Record a technician's observed test outcome and re-rank the hypotheses.

    This is a read-only Bayesian update of the ranking. It changes nothing about
    the installation and cannot introduce a fault that was not already a
    candidate.
    """
    active = _require(run_id)
    envelope = get_diagnosis(run_id)

    try:
        updated = apply_test_result(envelope.top_hypotheses, result)
    except PlannerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    active.test_results.append(result)
    performed = {r.test_id for r in active.test_results}
    next_test = plan_next_test(
        updated,
        maintenance_state=active.record.maintenance_state,
        already_performed=performed,
    )

    return {
        "run_id": run_id,
        "applied": result.model_dump(mode="json"),
        "hypotheses": [h.model_dump(mode="json") for h in updated],
        "next_test": next_test.model_dump(mode="json") if next_test else None,
        "tests_performed": sorted(performed),
        "notice": (
            "Hypothesis ranking updated from a reported observation. No change was made "
            "to the installation."
        ),
    }


# --------------------------------------------------------------------------- #
# Incidents and reports
# --------------------------------------------------------------------------- #


@app.get(f"{API_PREFIX}/incidents")
def list_incidents(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    return {"incidents": STORE.list_incidents(limit), "stats": STORE.stats()}


@app.get(f"{API_PREFIX}/incidents/{{incident_id}}")
def get_incident(incident_id: str) -> IncidentEnvelope:
    envelope = STORE.load_incident(incident_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail=f"incident {incident_id!r} not found")
    return envelope


@app.get(f"{API_PREFIX}/incidents/{{incident_id}}/report", response_class=HTMLResponse)
def get_report(incident_id: str) -> HTMLResponse:
    from flowlens.reporting.render import render_report_html

    envelope = STORE.load_incident(incident_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail=f"incident {incident_id!r} not found")
    return HTMLResponse(content=render_report_html(envelope))


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #


@app.websocket(f"{API_PREFIX}/runs/{{run_id}}/stream")
async def stream_run(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    active = RUNS.get(run_id)
    if active is None:
        await websocket.send_json({"type": "error", "detail": f"run {run_id} is not loaded"})
        await websocket.close()
        return

    try:
        await websocket.send_json(
            {
                "type": "start",
                "run_id": run_id,
                "scenario_id": active.record.scenario_id,
                "duration_ms": active.duration_ms,
            }
        )

        cursor = 0
        while cursor < active.duration_ms:
            if active.paused:
                await asyncio.sleep(0.1)
                continue

            nxt = min(cursor + STREAM_BATCH_MS, active.duration_ms)
            events = [
                e.model_dump(mode="json")
                for e in active.record.events
                if cursor < e.timestamp_ms <= nxt
            ]
            frames = [
                f.model_dump(mode="json")
                for f in active.record.frames
                if cursor < f.timestamp_ms <= nxt
            ]
            await websocket.send_json(
                {"type": "batch", "from_ms": cursor, "to_ms": nxt, "events": events, "frames": frames}
            )
            cursor = nxt
            active.cursor_ms = cursor
            await asyncio.sleep(STREAM_BATCH_MS / 1000.0 / PLAYBACK_SPEED)

        envelope = get_diagnosis(run_id)
        await websocket.send_json(
            {"type": "diagnosis", "envelope": envelope.model_dump(mode="json")}
        )
        await websocket.send_json({"type": "complete", "run_id": run_id})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover - transport level
        await websocket.send_json({"type": "error", "detail": str(exc)})
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass


# --------------------------------------------------------------------------- #
# Judge console (built assets). Dev still uses Vite on :5173.
# --------------------------------------------------------------------------- #

if CONSOLE_DIST.is_dir():
    assets = CONSOLE_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="console-assets")

    @app.get("/")
    def console_index() -> FileResponse:
        return FileResponse(CONSOLE_DIST / "index.html")
