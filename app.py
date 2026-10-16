from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from database import (
    DB_MODE, close_db, fetch_all, fetch_one, get_db, init_db,
    insert_demo_data, reset_demo_data
)
from scheduler_bridge import run_fcfs, run_priority_aging

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-key")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024


@app.teardown_appcontext
def teardown_db(_exception: BaseException | None = None) -> None:
    close_db()


def ticket_code(ticket_id: int | str) -> str:
    return f"HD-{int(ticket_id):04d}"


def parse_ticket_code(value: str) -> int | None:
    cleaned = (value or "").strip().upper()
    if cleaned.startswith("HD-"):
        cleaned = cleaned[3:]
    try:
        parsed = int(cleaned)
        return parsed if parsed > 0 else None
    except (ValueError, TypeError):
        return None


def format_dt(value: Any) -> str:
    if not value:
        return "Not estimated yet"
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    return dt.strftime("%d %b %Y, %I:%M %p")


WORK_START = time(8, 0)
WORK_END = time(19, 0)
WORK_MINUTES = 11 * 60

def next_work_time(value: datetime) -> datetime:
    if value.time() < WORK_START:
        return value.replace(hour=8, minute=0, second=0, microsecond=0)
    if value.time() >= WORK_END:
        next_day = value + timedelta(days=1)
        return next_day.replace(hour=8, minute=0, second=0, microsecond=0)
    return value

def add_work_minutes(value: datetime, minutes: int) -> datetime:
    current = next_work_time(value)
    remaining = max(0, int(minutes))
    while remaining:
        end = current.replace(hour=19, minute=0, second=0, microsecond=0)
        available = int((end - current).total_seconds() // 60)
        if remaining <= available:
            return current + timedelta(minutes=remaining)
        remaining -= available
        current = (current + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return current

def work_minutes_between(start: datetime, end: datetime) -> int:
    if end <= start:
        return 0
    total = 0
    day = start.date()
    while day <= end.date():
        window_start = datetime.combine(day, WORK_START)
        window_end = datetime.combine(day, WORK_END)
        overlap_start = max(start, window_start)
        overlap_end = min(end, window_end)
        if overlap_end > overlap_start:
            total += int((overlap_end - overlap_start).total_seconds() // 60)
        day += timedelta(days=1)
    return total

def wall_offset(anchor: datetime, value: datetime) -> int:
    return max(0, int((value - anchor).total_seconds() // 60))

def format_duration(value: Any) -> str:
    try:
        minutes = max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        minutes = 0
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

def as_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def fetch_categories() -> list[dict[str, Any]]:
    return fetch_all("SELECT category_id, category_name, description, default_priority, default_service_minutes FROM categories ORDER BY category_name")


def fetch_ticket(ticket_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """SELECT t.*, u.name AS requester_name, u.email AS requester_email,
                  c.category_name
           FROM tickets t
           JOIN users u ON u.user_id = t.user_id
           JOIN categories c ON c.category_id = t.category_id
           WHERE t.ticket_id = ?""", (ticket_id,)
    )


@app.route("/")
def index():
    categories = fetch_categories()
    recent = fetch_all(
        """SELECT t.ticket_id, t.title, t.priority, t.status, t.created_at,
                  c.category_name
           FROM tickets t JOIN categories c ON c.category_id=t.category_id
           ORDER BY t.created_at DESC, t.ticket_id DESC LIMIT 6"""
    )
    counts = fetch_one(
        """SELECT COUNT(*) AS total,
          SUM(CASE WHEN status IN ('NEW','READY','ASSIGNED','IN_PROGRESS','WAITING') THEN 1 ELSE 0 END) AS open_count,
          SUM(CASE WHEN status='RESOLVED' OR status='CLOSED' THEN 1 ELSE 0 END) AS resolved_count
          FROM tickets"""
    ) or {"total": 0, "open_count": 0, "resolved_count": 0}
    for item in recent:
        item["ticket_code"] = ticket_code(item["ticket_id"])
        item["created_label"] = format_dt(item["created_at"])
    return render_template("index.html", categories=categories, recent=recent, counts=counts, db_mode=DB_MODE)


@app.post("/submit")
def submit_ticket():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    location = (request.form.get("location_or_asset") or "").strip()
    raw_category = request.form.get("category_id", "")

    if not name or not email or not title or not description or not raw_category:
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("index") + "#submit-ticket")
    if len(name) > 100 or len(email) > 190 or len(title) > 160 or len(description) > 3000 or len(location) > 180:
        flash("One or more fields exceed the allowed length. Please shorten your entry.", "error")
        return redirect(url_for("index") + "#submit-ticket")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("index") + "#submit-ticket")
    try:
        category_id = int(raw_category)
    except ValueError:
        flash("Please choose a valid ticket category.", "error")
        return redirect(url_for("index") + "#submit-ticket")

    category = fetch_one("SELECT * FROM categories WHERE category_id = ?", (category_id,))
    if not category:
        flash("That category is unavailable. Please select another category.", "error")
        return redirect(url_for("index") + "#submit-ticket")

    conn = get_db()
    try:
        user = fetch_one("SELECT user_id FROM users WHERE email = ?", (email,))
        if user:
            user_id = user["user_id"]
            conn.execute("UPDATE users SET name = ? WHERE user_id = ?", (name, user_id))
        else:
            cursor = conn.execute(
                "INSERT INTO users (name, email, role, created_at) VALUES (?, ?, 'USER', ?)",
                (name, email, datetime.now().isoformat(timespec="seconds"))
            )
            user_id = cursor.lastrowid

        # Arrival offsets are relative simulation minutes. New tickets are appended
        # after the existing demo queue, so they do not jump ahead of older work.
        latest = fetch_one("SELECT MAX(arrival_offset) AS max_arrival FROM tickets WHERE status='READY'")
        arrival_offset = int(latest["max_arrival"] or 0) + (1 if latest and latest["max_arrival"] is not None else 0)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            """INSERT INTO tickets
               (user_id, category_id, title, description, location_or_asset, priority, status,
                estimated_service_minutes, arrival_offset, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'READY', ?, ?, ?, ?)""",
            (user_id, category_id, title, description, location, category["default_priority"],
             int(category["default_service_minutes"]), arrival_offset, now, now)
        )
        ticket_id = cursor.lastrowid
        conn.execute(
            """INSERT INTO ticket_history (ticket_id, old_status, new_status, changed_by, changed_at, note)
               VALUES (?, NULL, 'READY', 'SYSTEM', ?, 'Ticket submitted through the web form.')""",
            (ticket_id, now)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        app.logger.exception("Ticket creation failed")
        flash("The ticket could not be saved. Check the database connection and try again.", "error")
        return redirect(url_for("index") + "#submit-ticket")

    try:
        run_info = perform_fcfs_run()
        updated_ticket = fetch_ticket(ticket_id)
        if updated_ticket and updated_ticket.get("estimated_completion_at"):
            flash(f"Ticket {ticket_code(ticket_id)} was created. Preliminary completion estimate: {format_dt(updated_ticket['estimated_completion_at'])}. This estimate can change as the queue changes.", "success")
        else:
            flash(f"Ticket {ticket_code(ticket_id)} was created successfully. Run FCFS from the admin dashboard to calculate an estimate.", "success")
    except Exception:
        app.logger.exception("Ticket saved, but automatic FCFS estimate failed")
        flash(f"Ticket {ticket_code(ticket_id)} was created, but an estimate could not be calculated. The admin can run FCFS from the dashboard.", "success")
    return redirect(url_for("track_lookup", ticket_id=ticket_code(ticket_id)))


@app.route("/track", methods=["GET", "POST"])
def track_lookup():
    code = request.args.get("ticket_id", "")
    if request.method == "POST":
        code = request.form.get("ticket_id", "")
    if code:
        parsed = parse_ticket_code(code)
        if parsed:
            ticket = fetch_ticket(parsed)
            if ticket:
                ticket["ticket_code"] = ticket_code(ticket["ticket_id"])
                ticket["created_label"] = format_dt(ticket.get("created_at"))
                ticket["eta_label"] = format_dt(ticket.get("estimated_completion_at"))
                ticket["confirmed_label"] = format_dt(ticket.get("confirmed_target_at")) if ticket.get("confirmed_target_at") else "Not confirmed"
                history = fetch_all(
                    "SELECT old_status, new_status, changed_by, changed_at, note FROM ticket_history WHERE ticket_id=? ORDER BY history_id DESC LIMIT 20",
                    (parsed,)
                )
                for entry in history:
                    entry["changed_label"] = format_dt(entry.get("changed_at"))
                latest = fetch_one(
                    """SELECT sr.*, run.algorithm, run.engine_used, run.simulation_anchor_at
                       FROM scheduling_results sr JOIN scheduling_runs run ON run.run_id=sr.run_id
                       WHERE sr.ticket_id=? ORDER BY run.run_id DESC LIMIT 1""", (parsed,)
                )
                return render_template("track.html", ticket=ticket, history=history, result=latest, query=code, db_mode=DB_MODE)
        flash("No ticket was found. Check the ID, for example HD-0001.", "error")
    return render_template("track.html", ticket=None, history=[], result=None, query=code, db_mode=DB_MODE)


@app.route("/admin")
def admin_dashboard():
    latest_run = fetch_one("SELECT * FROM scheduling_runs ORDER BY run_id DESC LIMIT 1")
    tickets = fetch_all(
        """SELECT t.ticket_id, t.title, t.priority, t.status, t.estimated_service_minutes,
                  t.arrival_offset, t.estimated_wait_minutes, t.estimated_completion_at,
                  t.created_at, u.name AS requester_name, c.category_name
           FROM tickets t JOIN users u ON u.user_id=t.user_id
           JOIN categories c ON c.category_id=t.category_id
           ORDER BY CASE t.status WHEN 'READY' THEN 0 WHEN 'IN_PROGRESS' THEN 1 WHEN 'ASSIGNED' THEN 2 WHEN 'WAITING' THEN 3 ELSE 4 END,
                    t.priority ASC, t.ticket_id DESC LIMIT 100"""
    )
    for ticket in tickets:
        ticket["ticket_code"] = ticket_code(ticket["ticket_id"])
        ticket["eta_label"] = format_dt(ticket.get("estimated_completion_at"))
        ticket["created_label"] = format_dt(ticket.get("created_at"))

    ready_count = fetch_one("SELECT COUNT(*) AS n FROM tickets WHERE status='READY'")["n"]
    total_count = fetch_one("SELECT COUNT(*) AS n FROM tickets")["n"]
    open_count = fetch_one("SELECT COUNT(*) AS n FROM tickets WHERE status IN ('NEW','READY','ASSIGNED','IN_PROGRESS','WAITING')")["n"]
    resolved_count = fetch_one("SELECT COUNT(*) AS n FROM tickets WHERE status IN ('RESOLVED','CLOSED')")["n"]
    results = []
    if latest_run:
        results = fetch_all(
            """SELECT sr.*, t.title, t.priority FROM scheduling_results sr JOIN tickets t ON t.ticket_id=sr.ticket_id
               WHERE sr.run_id=? ORDER BY sr.queue_order ASC""", (latest_run["run_id"],)
        )
    run_data = None
    if latest_run:
        run_data = dict(latest_run)
        run_data["started_label"] = format_dt(run_data.get("started_at"))
        run_data["anchor_label"] = format_dt(run_data.get("simulation_anchor_at"))
        run_data["results"] = [dict(row) for row in results]
        run_data["aging_interval"] = 5
        try:
            run_anchor = datetime.fromisoformat(str(run_data.get("simulation_anchor_at")))
        except (TypeError, ValueError):
            run_anchor = datetime.now()
        run_data["anchor_iso"] = run_anchor.isoformat(timespec="seconds")
        for result in run_data["results"]:
            base_priority = int(result.get("priority", 3))
            result["effective_priority"] = max(1, base_priority - int(result["waiting_time"]) // run_data["aging_interval"]) if run_data.get("algorithm") == "Priority + Aging" else base_priority
            result["aging_boost"] = max(0, base_priority - result["effective_priority"])
            result["arrival_label"] = (run_anchor + timedelta(minutes=int(result["arrival_time"]))).strftime("%d %b %I:%M %p")
            result["start_label"] = (run_anchor + timedelta(minutes=int(result["start_time"]))).strftime("%d %b %I:%M %p")
            result["completion_label"] = (run_anchor + timedelta(minutes=int(result["completion_time"]))).strftime("%d %b %I:%M %p")
            result["service_label"] = format_duration(result["service_time"])
            result["waiting_label"] = format_duration(result["waiting_time"])
            result["turnaround_label"] = format_duration(result["turnaround_time"])
        for key in ("avg_waiting_time", "avg_response_time", "avg_turnaround_time"):
            run_data[key + "_label"] = format_duration(run_data.get(key))
    return render_template(
        "admin.html", tickets=tickets, latest_run=run_data, counts={"total": total_count, "ready": ready_count, "open": open_count, "resolved": resolved_count}, db_mode=DB_MODE
    )


def perform_scheduling_run(algorithm: str = "FCFS", aging_interval: int = 5):
    """Run the selected non-preemptive scheduler for READY tickets and save the snapshot."""
    jobs = fetch_all(
        """SELECT ticket_id, arrival_offset, estimated_service_minutes, priority
           FROM tickets WHERE status='READY' ORDER BY arrival_offset, ticket_id"""
    )
    if not jobs:
        return None

    anchor = datetime.now().replace(second=0, microsecond=0)
    if algorithm == "PRIORITY_AGING":
        results, engine_used = run_priority_aging(jobs, aging_interval)
        algorithm_label = "Priority + Aging"
        notes = f"Non-preemptive priority scheduling with aging every {aging_interval} working minutes; service is restricted to 08:00–19:00 and jobs that do not fit are deferred to the next workday. Simulation does not resolve tickets."
    else:
        results, engine_used = run_fcfs(jobs)
        algorithm_label = "FCFS"
        notes = "Single-server, non-preemptive FCFS simulation. Service is restricted to 08:00–19:00; jobs that do not fit are deferred to the next workday. Simulation completion does not resolve real tickets."
    jobs_by_id = {int(job["ticket_id"]): job for job in jobs}
    cursor_time = next_work_time(anchor)
    for result in results:
        job = jobs_by_id[int(result["ticket_id"])]
        service = int(job["estimated_service_minutes"])
        if service > WORK_MINUTES:
            raise ValueError(f"Ticket {ticket_code(job['ticket_id'])} needs more than 11 working hours and cannot fit in one workday.")
        arrival_dt = add_work_minutes(anchor, int(job["arrival_offset"]))
        start_dt = next_work_time(max(cursor_time, arrival_dt))
        day_end = start_dt.replace(hour=19, minute=0, second=0, microsecond=0)
        available = int((day_end - start_dt).total_seconds() // 60)
        if service > available:
            start_dt = (start_dt + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        completion_dt = start_dt + timedelta(minutes=service)
        result["arrival_time"] = wall_offset(anchor, arrival_dt)
        result["start_time"] = wall_offset(anchor, start_dt)
        result["completion_time"] = wall_offset(anchor, completion_dt)
        result["waiting_time"] = work_minutes_between(arrival_dt, start_dt)
        result["response_time"] = result["waiting_time"]
        result["turnaround_time"] = work_minutes_between(arrival_dt, completion_dt)
        cursor_time = completion_dt
    waits = [item["waiting_time"] for item in results]
    responses = [item["response_time"] for item in results]
    turnarounds = [item["turnaround_time"] for item in results]
    elapsed = max((item["completion_time"] for item in results), default=0)
    busy = sum(item["service_time"] for item in results)
    throughput = round(len(results) / elapsed, 4) if elapsed > 0 else 0.0
    utilization = round(100.0 * busy / elapsed, 2) if elapsed > 0 else 0.0
    finished = datetime.now()
    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO scheduling_runs
               (algorithm, engine_used, started_at, completed_at, simulation_anchor_at, ticket_count,
                avg_waiting_time, avg_response_time, avg_turnaround_time, throughput, utilization_percent, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (algorithm_label, engine_used, anchor.isoformat(timespec="seconds"), finished.isoformat(timespec="seconds"),
             anchor.isoformat(timespec="seconds"), len(results), round(sum(waits)/len(waits), 2),
             round(sum(responses)/len(responses), 2), round(sum(turnarounds)/len(turnarounds), 2),
             throughput, utilization, notes)
        )
        run_id = cursor.lastrowid
        for result in results:
            conn.execute(
                """INSERT INTO scheduling_results
                   (run_id, ticket_id, queue_order, arrival_time, service_time, start_time, completion_time,
                    waiting_time, turnaround_time, response_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, result["ticket_id"], result["queue_order"], result["arrival_time"], result["service_time"],
                 result["start_time"], result["completion_time"], result["waiting_time"], result["turnaround_time"], result["response_time"])
            )
            estimated_completion = anchor + timedelta(minutes=result["completion_time"])
            conn.execute(
                """UPDATE tickets SET estimated_wait_minutes=?, estimated_completion_at=?, updated_at=?
                   WHERE ticket_id=? AND status='READY'""",
                (result["waiting_time"], estimated_completion.isoformat(timespec="seconds"), finished.isoformat(timespec="seconds"), result["ticket_id"])
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"run_id": run_id, "ticket_count": len(results), "engine_used": engine_used, "algorithm": algorithm_label, "results": results}


@app.post("/admin/run-fcfs")
def admin_run_fcfs():
    return run_scheduler("FCFS")


@app.post("/admin/run-priority-aging")
def admin_run_priority_aging():
    return run_scheduler("PRIORITY_AGING")


def run_scheduler(algorithm: str):
    try:
        run_info = perform_scheduling_run(algorithm)
        if not run_info:
            flash("There are no READY tickets to schedule. Add a ticket or reset the demo data.", "error")
        else:
            flash(f"{run_info['algorithm']} finished for {run_info['ticket_count']} READY tickets using {run_info['engine_used']}. Results saved; tickets remain READY until a technician changes their status.", "success")
    except Exception as exc:
        app.logger.exception("Scheduler failed")
        flash(f"Scheduling could not run: {exc}", "error")
    return redirect(url_for("admin_dashboard") + "#scheduler")


@app.post("/admin/reset-demo")
def admin_reset_demo():
    try:
        reset_demo_data()
        insert_demo_data(force=True)
        flash("Demo data reset to the sample scenario. This reset is for a local demo database; it removes tickets created in this database.", "success")
    except Exception:
        app.logger.exception("Demo reset failed")
        flash("Could not reset the demo data. Check the database connection and logs.", "error")
    return redirect(url_for("admin_dashboard"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The page you requested was not found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="Something went wrong. Check the terminal for the server error."), 500


with app.app_context():
    init_db()
    insert_demo_data(force=False)


if __name__ == "__main__":
    print(f"Help Desk running with {DB_MODE} database mode.")
    print("Open http://127.0.0.1:5000")
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
