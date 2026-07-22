# dash_app/backend/jobs.py
# File-backed job runner for the app's long tasks (snapshot refresh, plan refresh).
# Same design as the overbooking tool:
#
# Why not Dash background callbacks: their progress state lives inside the
# callback context and dies when the user navigates away - the UI then shows a
# stuck loading bar while the work keeps running invisibly. Here every job
# writes its state to data/jobs/<name>.json; any page polls that file with a
# dcc.Interval and renders real progress, success or error - across page
# changes AND app restarts. One job per name at a time; jobs are daemon threads.

from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

Progress = Callable[[str, float], None]

_JOBS_DIR = Path(__file__).resolve().parents[2] / "data" / "jobs"
_LOCK = threading.Lock()
_THREADS: dict[str, threading.Thread] = {}
_CANCEL: dict[str, threading.Event] = {}


class JobCancelled(Exception):
    """Raised inside a job (via the progress checkpoint) when the user cancels."""


def _job_path(name: str) -> Path:
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return _JOBS_DIR / f"{name}.json"


def _cancel_path(name: str) -> Path:
    return _job_path(name).with_suffix(".cancel")


def _write(name: str, state: dict) -> None:
    try:
        _job_path(name).write_text(json.dumps(state))
    except Exception:  # noqa: BLE001 - a status write must never kill the job
        pass


def read(name: str) -> dict:
    """Current state: {status: idle|running|done|error|cancelled, progress, message,
    started, finished, result, error}. A file that says 'running' without a live
    thread (app restart / crash) is flipped to a loud error instead of an
    eternal loading bar."""
    p = _job_path(name)
    if not p.exists():
        return {"status": "idle"}
    try:
        state = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {"status": "idle"}
    if state.get("status") == "running":
        t = _THREADS.get(name)
        if t is None or not t.is_alive():
            state["status"] = "error"
            state["error"] = ("Die App wurde neu gestartet, während dieser Job lief. "
                              "Bitte erneut starten.")
            state["finished"] = time.time()
            _write(name, state)
    return state


def running(name: str) -> bool:
    return read(name).get("status") == "running"


def cancel(name: str) -> bool:
    """Cooperative cancel: the job stops at its next progress checkpoint and is
    marked 'cancelled' without writing its result, so previous data survives.
    File-based (data/jobs/<name>.cancel holds the start timestamp) so it works
    across worker processes; the in-process Event covers the single-worker case."""
    st = read(name)
    if st.get("status") != "running":
        return False
    try:
        _cancel_path(name).write_text(str(st.get("started", "")))
    except Exception:  # noqa: BLE001
        pass
    ev = _CANCEL.get(name)
    if ev is not None:
        ev.set()
    return True


def _cancel_requested(name: str, started, ev: threading.Event | None) -> bool:
    if ev is not None and ev.is_set():
        return True
    try:
        p = _cancel_path(name)
        return p.exists() and p.read_text().strip() == str(started)
    except Exception:  # noqa: BLE001
        return False


def start(name: str, fn: Callable, *args, **kwargs) -> bool:
    """Run fn(progress, *args, **kwargs) in a daemon thread; progress(msg, frac)
    streams into the status file. Returns False if `name` is already running."""
    with _LOCK:
        if running(name):
            return False
        cancel_ev = threading.Event()
        _CANCEL[name] = cancel_ev
        state = {"status": "running", "progress": 0.0, "message": "starte …",
                 "started": time.time(), "finished": None, "result": None, "error": None}
        _write(name, state)

        def progress(msg: str, frac: float) -> None:
            # Cancel checkpoint BEFORE reporting more work, so the job aborts
            # before it writes anything and the previous data survives.
            if _cancel_requested(name, state["started"], cancel_ev):
                raise JobCancelled()
            state["message"] = str(msg)
            state["progress"] = max(0.0, min(1.0, float(frac)))
            _write(name, state)

        def run() -> None:
            try:
                result = fn(progress, *args, **kwargs)
                state.update(status="done", progress=1.0, message="fertig",
                             finished=time.time(), result=result)
            except JobCancelled:
                state.update(status="cancelled", progress=0.0, finished=time.time(),
                             message="Abgebrochen — vorherige Daten bleiben erhalten.",
                             result=None)
            except Exception as e:  # noqa: BLE001 - jobs fail LOUDLY
                state.update(status="error", finished=time.time(),
                             error=f"{type(e).__name__}: {str(e)[:600]}",
                             trace=traceback.format_exc()[-2000:])
            _write(name, state)

        t = threading.Thread(target=run, daemon=True, name=f"job-{name}")
        _THREADS[name] = t
        t.start()
        return True
