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


def _compile_rr_cpp() -> tuple[Path | None, str | None]:
    source = ROOT / "round_robin_scheduler.cpp"
    compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        return None, "C++17 compiler not found."
    BUILD_DIR.mkdir(exist_ok=True)
    binary = BUILD_DIR / ("round_robin_scheduler.exe" if os.name == "nt" else "round_robin_scheduler")
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        try:
            proc = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", str(source), "-o", str(binary)],
                                  capture_output=True, text=True, timeout=45, cwd=str(ROOT))
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"Could not invoke C++ compiler: {exc}"
        if proc.returncode != 0:
            return None, f"C++ compilation failed: {(proc.stderr or proc.stdout)[-1000:]}"
    return binary, None


def run_round_robin(jobs: list[dict[str, Any]], quantum: int, context_switch_overhead: int = 0) -> tuple[list[dict[str, Any]], str, int]:
    if not 1 <= int(quantum) <= 240:
        raise ValueError("Time quantum must be between 1 and 240 minutes.")
    if not 0 <= int(context_switch_overhead) <= 30:
        raise ValueError("Context-switch overhead must be between 0 and 30 minutes.")
    if any(int(j["estimated_service_minutes"]) <= 0 for j in jobs):
        raise ValueError("Every READY ticket must have a positive service duration.")
    if any(int(j["arrival_offset"]) < 0 for j in jobs):
        raise ValueError("Arrival times cannot be negative.")
    binary, error = _compile_rr_cpp()
    if binary:
        payload = [str(len(jobs))]
        payload.extend(f"{int(j['ticket_id'])} {int(j['arrival_offset'])} {int(j['estimated_service_minutes'])}" for j in jobs)
        try:
            proc = subprocess.run([str(binary), str(int(quantum)), str(int(context_switch_overhead))], input="\n".join(payload)+"\n",
                                  capture_output=True, text=True, timeout=15, cwd=str(ROOT))
            if proc.returncode == 0:
                rows: dict[int, dict[str, Any]] = {}
                segments: dict[int, list[dict[str, int]]] = {}
                switches = 0
                for line in proc.stdout.splitlines():
                    parts = line.split()
                    if not parts: continue
                    if parts[0] == "C": switches = int(parts[1])
                    elif parts[0] == "S":
                        tid, start, end = map(int, parts[1:4])
                        segments.setdefault(tid, []).append({"start_time": start, "end_time": end})
                    elif parts[0] == "R":
                        vals = list(map(int, parts[1:]))
                        tid, arrival, service, start, completion, waiting, turnaround, response, order = vals
                        rows[tid] = {"ticket_id": tid, "arrival_time": arrival, "service_time": service,
                                     "start_time": start, "completion_time": completion, "waiting_time": waiting,
                                     "turnaround_time": turnaround, "response_time": response, "queue_order": order}
                if len(rows) == len(jobs):
                    for tid, row in rows.items(): row["segments"] = segments.get(tid, [])
                    return sorted(rows.values(), key=lambda x: x["queue_order"]), "C++17 Round Robin executable", switches
                error = "Round Robin C++ output was incomplete."
            else:
                error = f"Round Robin C++ scheduler failed: {proc.stderr[-1000:]}"
        except (subprocess.TimeoutExpired, OSError) as exc:
            error = f"Round Robin C++ execution failed: {exc}"
    results, switches = _python_round_robin(jobs, int(quantum), int(context_switch_overhead))
    return results, f"Python Round Robin fallback — {error or 'C++ scheduler unavailable'}", switches


def _python_round_robin(jobs: list[dict[str, Any]], quantum: int, overhead: int = 0):
    ordered = sorted((dict(j) for j in jobs), key=lambda x: (int(x["arrival_offset"]), int(x["ticket_id"])))
    remaining = {int(j["ticket_id"]): int(j["estimated_service_minutes"]) for j in ordered}
    by_id = {int(j["ticket_id"]): j for j in ordered}
    segments: dict[int, list[dict[str, int]]] = {int(j["ticket_id"]): [] for j in ordered}
    first: dict[int, int] = {}
    completion: dict[int, int] = {}
    ready: list[int] = []
    cursor = 0
    clock = 0
    previous = None
    switches = 0
    while len(completion) < len(ordered):
        while cursor < len(ordered) and int(ordered[cursor]["arrival_offset"]) <= clock:
            ready.append(int(ordered[cursor]["ticket_id"]))
            cursor += 1
        if not ready:
            if cursor < len(ordered):
                clock = max(clock, int(ordered[cursor]["arrival_offset"]))
                continue
            break
        tid = ready.pop(0)
        if previous is not None and previous != tid:
            switches += 1
            clock += overhead
        first.setdefault(tid, clock)
        duration = min(quantum, remaining[tid])
        start = clock
        clock += duration
        segments[tid].append({"start_time": start, "end_time": clock})
        remaining[tid] -= duration
        while cursor < len(ordered) and int(ordered[cursor]["arrival_offset"]) <= clock:
            ready.append(int(ordered[cursor]["ticket_id"]))
            cursor += 1
        if remaining[tid] > 0:
            ready.append(tid)
        else:
            completion[tid] = clock
        previous = tid
    results = []
    for order, tid in enumerate(sorted(first, key=lambda x: (first[x], x)), 1):
        job = by_id[tid]
        arrival = int(job["arrival_offset"])
        service = int(job["estimated_service_minutes"])
        done = completion[tid]
        results.append({"ticket_id": tid, "arrival_time": arrival, "service_time": service,
                        "start_time": first[tid], "completion_time": done,
                        "waiting_time": done-arrival-service, "turnaround_time": done-arrival,
                        "response_time": first[tid]-arrival, "queue_order": order,
                        "segments": segments[tid]})
    return results, switches
