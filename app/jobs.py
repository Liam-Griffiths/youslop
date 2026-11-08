"""Background job runner with a progress log the UI can poll."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Any, Callable

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
MAX_JOBS = 60


class JobCancelled(Exception):
    """A cooperative cancellation at a job's progress checkpoint."""


def start(kind: str, project_id: str, fn: Callable[[Callable[[str], None]], Any],
          *, cancellable: bool = False) -> str:
    """Run `fn(progress)` on a worker thread. Returns the job id immediately."""
    jid = f"j{uuid.uuid4().hex[:10]}"
    job = {
        "id": jid, "kind": kind, "project_id": project_id, "state": "running",
        "log": [], "error": "", "result": None,
        "started_at": time.time(), "finished_at": 0.0,
        "cancellable": cancellable, "cancel_requested": False,
    }
    with _LOCK:
        _JOBS[jid] = job
        if len(_JOBS) > MAX_JOBS:
            for old in sorted(_JOBS.values(), key=lambda j: j["started_at"])[:10]:
                if old["state"] != "running":
                    _JOBS.pop(old["id"], None)

    def progress(message: str) -> None:
        with _LOCK:
            if job["cancel_requested"]:
                raise JobCancelled()
            job["log"].append({"t": time.time(), "m": str(message)})
            del job["log"][:-400]

    def runner() -> None:
        try:
            result = fn(progress)
            with _LOCK:
                job["result"] = result
                job["state"] = "done"
        except JobCancelled:
            with _LOCK:
                job["state"] = "cancelled"
        except Exception as exc:
            traceback.print_exc()
            with _LOCK:
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["state"] = "error"
                job["log"].append({"t": time.time(), "m": f"FAILED: {exc}"})
        finally:
            with _LOCK:
                job["finished_at"] = time.time()

    threading.Thread(target=runner, name=f"job-{kind}", daemon=True).start()
    return jid


def get(jid: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(jid)
        return dict(job) if job else None


def cancel(jid: str) -> dict:
    """Request cancellation; work stops only at the next progress call."""
    with _LOCK:
        job = _JOBS.get(jid)
        if job is None:
            raise KeyError(jid)
        if not job["cancellable"] or job["state"] != "running":
            raise ValueError("Job cannot be cancelled")
        job["cancel_requested"] = True
        return {"id": jid, "state": job["state"], "cancel_requested": True}


def recent() -> list[dict]:
    """Small summaries, newest first, without log bodies or results."""
    with _LOCK:
        now = time.time()
        return [{key: j[key] for key in
                 ("id", "kind", "project_id", "state", "cancellable")} | {
                     "last_log_line": j["log"][-1]["m"] if j["log"] else "",
                     "elapsed": round((j["finished_at"] or now) - j["started_at"], 1),
                 } for j in sorted(_JOBS.values(), key=lambda j: j["started_at"], reverse=True)]


def active_for(project_id: str) -> list[dict]:
    with _LOCK:
        return [dict(j) for j in _JOBS.values()
                if j["project_id"] == project_id and j["state"] == "running"]


def running() -> list[dict]:
    """Every job still running, across every project.

    What the desktop shell checks before it lets the window close — quitting
    mid-render kills the ffmpeg process with it, and there is no window-close
    equivalent of the browser's "leave site?" prompt to catch that by accident.
    """
    with _LOCK:
        return [dict(j) for j in _JOBS.values() if j["state"] == "running"]
