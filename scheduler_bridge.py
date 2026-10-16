from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CPP_SOURCE = ROOT / "fcfs_scheduler.cpp"
BUILD_DIR = ROOT / "build"


def _binary_path() -> Path:
    return BUILD_DIR / ("fcfs_scheduler.exe" if os.name == "nt" else "fcfs_scheduler")


def _compile_cpp() -> tuple[Path | None, str | None]:
    compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        return None, "C++17 compiler not found (install MinGW-w64 g++ or clang++)."
    BUILD_DIR.mkdir(exist_ok=True)
    binary = _binary_path()
    needs_build = not binary.exists() or binary.stat().st_mtime < CPP_SOURCE.stat().st_mtime
    if needs_build:
        command = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", str(CPP_SOURCE), "-o", str(binary)]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=45, cwd=str(ROOT))
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"Could not invoke the C++ compiler: {exc}"
        if proc.returncode != 0:
            return None, f"C++ compilation failed: {(proc.stderr or proc.stdout)[-1200:]}"
    return binary, None


def run_fcfs(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, int]], str]:
    return _run_scheduler(jobs, aging=False, aging_interval=5)


def run_priority_aging(jobs: list[dict[str, Any]], aging_interval: int = 5) -> tuple[list[dict[str, int]], str]:
    if aging_interval <= 0:
        raise ValueError("Aging interval must be a positive number of minutes.")
    return _run_scheduler(jobs, aging=True, aging_interval=aging_interval)


def _run_scheduler(jobs: list[dict[str, Any]], aging: bool, aging_interval: int) -> tuple[list[dict[str, int]], str]:
    if any(int(j["estimated_service_minutes"]) <= 0 for j in jobs):
        raise ValueError("Every READY ticket must have a positive estimated service duration.")
    if any(int(j.get("priority", 3)) not in (1, 2, 3, 4) for j in jobs):
        raise ValueError("Ticket priority must be between 1 (highest) and 4 (lowest).")
    binary, compile_error = _compile_cpp()
    if binary:
        input_lines = [str(len(jobs))]
        for job in jobs:
            input_lines.append(
                f"{int(job['ticket_id'])} {int(job['arrival_offset'])} "
                f"{int(job['estimated_service_minutes'])} {int(job.get('priority', 3))}"
            )
        payload = "\n".join(input_lines) + "\n"
        try:
            command = [str(binary), "--aging", str(aging_interval)] if aging else [str(binary)]
            proc = subprocess.run(command, input=payload, capture_output=True, text=True,
                                  timeout=10, cwd=str(ROOT))
        except (subprocess.TimeoutExpired, OSError) as exc:
            proc = None
            run_error = f"C++ scheduler execution failed: {exc}"
        else:
            run_error = f"C++ scheduler exited with code {proc.returncode}: {proc.stderr[-1000:]}"
        if proc and proc.returncode == 0:
            try:
                return _parse_output(proc.stdout), "C++17 executable"
            except (ValueError, KeyError) as exc:
                compile_error = f"Could not parse C++ output: {exc}"
        else:
            compile_error = run_error

    # Keep the demo usable if the machine doesn't have a C++ compiler. The admin
    # page explicitly labels this as a Python fallback instead of pretending C++ ran.
    results = _python_priority_aging(jobs, aging_interval) if aging else _python_fcfs(jobs)
    if compile_error:
        engine = f"Python fallback — {compile_error}"
    else:
        engine = "Python fallback — C++ scheduler unavailable"
    return results, engine


def _parse_output(output: str) -> list[dict[str, int]]:
    results = []
    for line in output.splitlines():
        if not line.strip():
            continue
        values = [int(part) for part in line.strip().split()]
        if len(values) != 9:
            raise ValueError(f"Expected 9 columns, received {len(values)}")
        ticket_id, arrival, service, start, completion, waiting, turnaround, response, order = values
        results.append({
            "ticket_id": ticket_id, "arrival_time": arrival, "service_time": service,
            "start_time": start, "completion_time": completion, "waiting_time": waiting,
            "turnaround_time": turnaround, "response_time": response, "queue_order": order,
        })
    return results


def _python_priority_aging(jobs: list[dict[str, Any]], aging_interval: int) -> list[dict[str, int]]:
    pending = [dict(job) for job in jobs]
    clock = 0
    out = []
    while pending:
        ready = [job for job in pending if int(job["arrival_offset"]) <= clock]
        if not ready:
            clock = min(int(job["arrival_offset"]) for job in pending)
            ready = [job for job in pending if int(job["arrival_offset"]) <= clock]
        job = min(
            ready,
            key=lambda item: (
                max(1, int(item.get("priority", 3)) - (clock - int(item["arrival_offset"])) // aging_interval),
                int(item["arrival_offset"]),
                int(item["ticket_id"]),
            ),
        )
        arrival = int(job["arrival_offset"])
        service = int(job["estimated_service_minutes"])
        start = max(clock, arrival)
        completion = start + service
        waiting = start - arrival
        out.append({
            "ticket_id": int(job["ticket_id"]), "arrival_time": arrival,
            "service_time": service, "start_time": start, "completion_time": completion,
            "waiting_time": waiting, "turnaround_time": completion - arrival,
            "response_time": waiting, "queue_order": len(out) + 1,
        })
        clock = completion
        pending.remove(job)
    return out


def _python_fcfs(jobs: list[dict[str, Any]]) -> list[dict[str, int]]:
    ordered = sorted(jobs, key=lambda j: (int(j["arrival_offset"]), int(j["ticket_id"])))
    clock = 0
    out = []
    for order, job in enumerate(ordered, 1):
        arrival = int(job["arrival_offset"])
        service = int(job["estimated_service_minutes"])
        start = max(clock, arrival)
        completion = start + service
        out.append({
            "ticket_id": int(job["ticket_id"]), "arrival_time": arrival,
            "service_time": service, "start_time": start, "completion_time": completion,
            "waiting_time": start-arrival, "turnaround_time": completion-arrival,
            "response_time": start-arrival, "queue_order": order,
        })
        clock = completion
    return out
