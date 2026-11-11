from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import wraps
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for, session
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from database import (
    DB_MODE, close_db, fetch_all, fetch_one, get_db, init_db,
    insert_demo_data, reset_demo_data
)
from scheduler_bridge import run_fcfs, run_priority_aging, run_round_robin

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-key")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def technician_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("technician_id"):
            return redirect(url_for("technician_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def map_work_interval(anchor: datetime, start_offset: int, end_offset: int) -> list[dict[str, int]]:
    """Map a working-minute interval to wall-clock offsets, splitting at 19:00."""
    current = add_work_minutes(anchor, int(start_offset))
    remaining = max(0, int(end_offset) - int(start_offset))
    mapped = []
    while remaining > 0:
        close = current.replace(hour=19, minute=0, second=0, microsecond=0)
        available = max(0, int((close - current).total_seconds() // 60))
        if available <= 0:
            current = (current + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            continue
        portion = min(remaining, available)
        end = current + timedelta(minutes=portion)
        mapped.append({"start_time": wall_offset(anchor, current), "end_time": wall_offset(anchor, end)})
        remaining -= portion
        if remaining:
            current = (current + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return mapped


@app.before_request
def csrf_guard():
    if "_csrf_token" not in session:
        import secrets
        session["_csrf_token"] = secrets.token_urlsafe(32)
    if request.method == "POST":
        import hmac
        submitted = request.form.get("_csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not submitted or not expected or not hmac.compare_digest(submitted, expected):
            return render_template("error.html", code=400, message="The form session expired or could not be verified. Reload the page and try again."), 400


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
    return dt.strftime("%d %b %Y, %H:%M")


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


app.jinja_env.filters["duration"] = format_duration


def parse_duration_input(value: Any, default: int = 0) -> int:
    """Parse a duration entered as HH:MM; accept legacy integer minutes as fallback."""
    raw = str(value or "").strip()
    if not raw:
        return default
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("Enter time in HH:MM format, for example 00:04.")
        hours, minutes = map(int, parts)
        if minutes > 59:
            raise ValueError("The minutes portion must be between 00 and 59.")
        return hours * 60 + minutes
    if raw.isdigit():
        return int(raw)
    raise ValueError("Enter time in HH:MM format, for example 00:04.")

def as_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def fetch_categories() -> list[dict[str, Any]]:
    return fetch_all("SELECT category_id, category_name, description, default_priority, default_service_minutes FROM categories ORDER BY category_name")


def fetch_ticket(ticket_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """SELECT t.*, u.name AS requester_name, u.email AS requester_email,
                  c.category_name, o.organization_name
           FROM tickets t
           JOIN users u ON u.user_id = t.user_id
           JOIN categories c ON c.category_id = t.category_id
           LEFT JOIN organizations o ON o.organization_id=t.organization_id
           WHERE t.ticket_id = ?""", (ticket_id,)
    )


@app.route("/")
def index():
    categories = fetch_categories()
    # The public landing page does not expose ticket totals or cross-organization records.
    organizations = fetch_all("SELECT organization_id, organization_name FROM organizations WHERE is_active=1 ORDER BY organization_name")
    return render_template("index.html", categories=categories, organizations=organizations, db_mode=DB_MODE)


@app.post("/submit")
def submit_ticket():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    location = (request.form.get("location_or_asset") or "").strip()
    raw_category = request.form.get("category_id", "")
    raw_org = request.form.get("organization_id", "")

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

    try:
        organization_id = int(raw_org) if raw_org else 0
    except ValueError:
        organization_id = 0
    organization = fetch_one("SELECT organization_id FROM organizations WHERE organization_id=? AND is_active=1", (organization_id,)) if organization_id else fetch_one("SELECT organization_id FROM organizations WHERE is_active=1 ORDER BY organization_id LIMIT 1")
    category = fetch_one("SELECT * FROM categories WHERE category_id = ?", (category_id,))
    if not category or not organization:
        flash("That category is unavailable. Please select another category.", "error")
        return redirect(url_for("index") + "#submit-ticket")

    conn = get_db()
    try:
        now = datetime.now().isoformat(timespec="seconds")
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

        if DB_MODE == "mysql":
            conn.execute("INSERT IGNORE INTO organization_users (organization_id,user_id,joined_at) VALUES (?,?,?)", (organization["organization_id"],user_id,now))
        else:
            conn.execute("INSERT OR IGNORE INTO organization_users (organization_id,user_id,joined_at) VALUES (?,?,?)", (organization["organization_id"],user_id,now))
        conn.execute("UPDATE users SET organization_id=? WHERE user_id=? AND organization_id IS NULL", (organization["organization_id"],user_id))

        # Arrival offsets are relative simulation minutes. New tickets are appended
        # after the existing demo queue, so they do not jump ahead of older work.
        latest = fetch_one("SELECT MAX(arrival_offset) AS max_arrival FROM tickets WHERE status='READY'")
        arrival_offset = int(latest["max_arrival"] or 0) + (1 if latest and latest["max_arrival"] is not None else 0)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            """INSERT INTO tickets
               (user_id, category_id, organization_id, title, description, location_or_asset, priority, status,
                estimated_service_minutes, arrival_offset, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'READY', ?, ?, ?, ?)""",
            (user_id, category_id, organization["organization_id"], title, description, location, category["default_priority"],
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
        run_info = perform_scheduling_run("FCFS")
        updated_ticket = fetch_ticket(ticket_id)
        if updated_ticket and updated_ticket.get("estimated_completion_at"):
            flash(f"Ticket {ticket_code(ticket_id)} was created. Preliminary completion estimate: {format_dt(updated_ticket['estimated_completion_at'])}. This estimate can change as the queue changes.", "success")
        else:
            flash(f"Ticket {ticket_code(ticket_id)} was created successfully. Run FCFS from the admin dashboard to calculate an estimate.", "success")
    except Exception:
        app.logger.exception("Ticket saved, but automatic FCFS estimate failed")
        flash(f"Ticket {ticket_code(ticket_id)} was created, but an estimate could not be calculated. The admin can run FCFS from the dashboard.", "success")
    session["ticket_lookup"] = {"ticket_id": ticket_code(ticket_id), "email": email}
    return redirect(url_for("track_lookup"))


@app.route("/track", methods=["GET", "POST"])
def track_lookup():
    code = request.args.get("ticket_id", "")
    email = (request.args.get("email", "") or request.form.get("email", "")).strip().lower()
    if request.method == "GET" and not code and session.get("ticket_lookup"):
        saved_lookup = session.pop("ticket_lookup")
        code = saved_lookup.get("ticket_id", "")
        email = (saved_lookup.get("email", "") or "").strip().lower()
    if request.method == "POST":
        code = request.form.get("ticket_id", "")
    if code:
        parsed = parse_ticket_code(code)
        if parsed:
            ticket = fetch_ticket(parsed)
            if ticket and (session.get("admin_authenticated") or (email and email == str(ticket.get("requester_email", "")).lower())):
                ticket["ticket_code"] = ticket_code(ticket["ticket_id"])
                ticket["created_label"] = format_dt(ticket.get("created_at"))
                ticket["eta_label"] = format_dt(ticket.get("estimated_completion_at"))
                ticket["confirmed_label"] = format_dt(ticket.get("confirmed_target_at")) if ticket.get("confirmed_target_at") else "Not confirmed"
                ticket["service_rating_exists"] = bool(fetch_one("SELECT rating_id FROM service_ratings WHERE ticket_id=?", (parsed,)))
                assignment = fetch_one("SELECT ta.technician_id, te.name AS technician_name FROM ticket_assignments ta JOIN technicians te ON te.technician_id=ta.technician_id WHERE ta.ticket_id=? ORDER BY ta.assignment_id DESC LIMIT 1", (parsed,))
                ticket["assigned_technician"] = assignment
                ticket["technician_rating_exists"] = bool(fetch_one("SELECT rating_id FROM technician_ratings WHERE ticket_id=?", (parsed,)))
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
                if latest:
                    latest = dict(latest)
                    for field in ("waiting_time", "service_time", "turnaround_time", "response_time"):
                        latest[field + "_label"] = format_duration(latest.get(field))
                return render_template("track.html", ticket=ticket, history=history, result=latest, query=code, email=email, db_mode=DB_MODE)
        flash("No ticket was found. Check the ID, for example HD-0001.", "error")
    return render_template("track.html", ticket=None, history=[], result=None, query=code, email=email, db_mode=DB_MODE)


@app.route("/admin")
@admin_required
def admin_dashboard():
    latest_run = fetch_one("SELECT * FROM scheduling_runs ORDER BY run_id DESC LIMIT 1")
    tickets = fetch_all(
        """SELECT t.ticket_id, t.title, t.priority, t.status, t.estimated_service_minutes,
                  t.arrival_offset, t.estimated_wait_minutes, t.estimated_completion_at,
                  t.created_at, u.name AS requester_name, c.category_name, o.organization_name,
                  ta.technician_id AS assigned_technician_id, te.name AS assigned_technician_name
           FROM tickets t JOIN users u ON u.user_id=t.user_id
           JOIN categories c ON c.category_id=t.category_id
           LEFT JOIN organizations o ON o.organization_id=t.organization_id
           LEFT JOIN ticket_assignments ta ON ta.ticket_id=t.ticket_id AND ta.is_active=1
           LEFT JOIN technicians te ON te.technician_id=ta.technician_id
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
        for item in run_data["results"]:
            item["segments"] = fetch_all("SELECT start_time,end_time FROM scheduling_segments WHERE result_id=? ORDER BY segment_number", (item["result_id"],))
            if not item["segments"]:
                item["segments"] = [{"start_time": item["start_time"], "end_time": item["completion_time"]}]
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
            result["arrival_label"] = (run_anchor + timedelta(minutes=int(result["arrival_time"]))).strftime("%d %b %H:%M")
            result["start_label"] = (run_anchor + timedelta(minutes=int(result["start_time"]))).strftime("%d %b %H:%M")
            result["completion_label"] = (run_anchor + timedelta(minutes=int(result["completion_time"]))).strftime("%d %b %H:%M")
            result["service_label"] = format_duration(result["service_time"])
            result["waiting_label"] = format_duration(result["waiting_time"])
            result["response_label"] = format_duration(result["response_time"])
            result["turnaround_label"] = format_duration(result["turnaround_time"])
        for key in ("avg_waiting_time", "avg_response_time", "avg_turnaround_time"):
            run_data[key + "_label"] = format_duration(run_data.get(key))
    technicians = fetch_all("SELECT * FROM v_technician_performance ORDER BY is_active DESC,name")
    technician_rating_details = fetch_all("""SELECT tr.rating_id,tr.rating,tr.feedback,tr.created_at,
        te.name AS technician_name,t.ticket_id,t.title,o.organization_name
        FROM technician_ratings tr JOIN technicians te ON te.technician_id=tr.technician_id
        JOIN tickets t ON t.ticket_id=tr.ticket_id LEFT JOIN organizations o ON o.organization_id=t.organization_id
        ORDER BY tr.created_at DESC,tr.rating_id DESC LIMIT 50""")
    for rating in technician_rating_details:
        rating["created_label"] = format_dt(rating.get("created_at"))
    organizations = fetch_all("""SELECT o.organization_id,o.organization_name,o.contact_email,o.is_active,
        COUNT(t.ticket_id) AS ticket_count,
        SUM(CASE WHEN t.status IN ('NEW','READY','ASSIGNED','IN_PROGRESS','WAITING') THEN 1 ELSE 0 END) AS open_count,
        SUM(CASE WHEN t.status IN ('RESOLVED','CLOSED') THEN 1 ELSE 0 END) AS resolved_count
        FROM organizations o LEFT JOIN tickets t ON t.organization_id=o.organization_id
        GROUP BY o.organization_id,o.organization_name,o.contact_email,o.is_active ORDER BY o.organization_name""")
    service_ratings = fetch_all("SELECT category_id,category_name,ROUND(avg_rating,2) AS avg_rating,rating_count FROM v_service_category_performance ORDER BY category_name")
    resources = fetch_all("""SELECT r.resource_id,r.resource_name,r.total_quantity,r.description,o.organization_name,
        r.total_quantity-COALESCE(SUM(CASE WHEN ra.status='ALLOCATED' THEN ra.quantity ELSE 0 END),0) AS available_quantity
        FROM resources r LEFT JOIN resource_allocations ra ON ra.resource_id=r.resource_id
        LEFT JOIN organizations o ON o.organization_id=r.organization_id
        GROUP BY r.resource_id,r.resource_name,r.total_quantity,r.description,o.organization_name ORDER BY r.resource_name""")
    comparison = build_comparison()
    allocations = fetch_all("""SELECT ra.allocation_id,ra.quantity,ra.status,ra.allocated_at,ra.released_at,
        te.name AS technician_name,r.resource_name,t.ticket_id
        FROM resource_allocations ra JOIN technicians te ON te.technician_id=ra.technician_id
        JOIN resources r ON r.resource_id=ra.resource_id LEFT JOIN tickets t ON t.ticket_id=ra.ticket_id
        ORDER BY ra.allocated_at DESC LIMIT 100""")
    for allocation in allocations:
        allocation["allocated_label"] = format_dt(allocation.get("allocated_at"))
        allocation["released_label"] = format_dt(allocation.get("released_at")) if allocation.get("released_at") else None
    return render_template(
        "admin.html", tickets=tickets, latest_run=run_data,
        counts={"total": total_count, "ready": ready_count, "open": open_count, "resolved": resolved_count},
        technicians=technicians, technician_rating_details=technician_rating_details,
        organizations=organizations, service_ratings=service_ratings,
        resources=resources, allocations=allocations, comparison=comparison, db_mode=DB_MODE
    )


def perform_scheduling_run(algorithm: str = "FCFS", aging_interval: int = 5, quantum: int = 4, context_switch_overhead: int = 0):
    """Run the selected scheduling policy for READY tickets and persist its result snapshot."""
    jobs = fetch_all(
        """SELECT ticket_id, arrival_offset, estimated_service_minutes, priority
           FROM tickets WHERE status='READY' ORDER BY arrival_offset, ticket_id"""
    )
    if not jobs:
        return None

    anchor = datetime.now().replace(second=0, microsecond=0)
    context_switches = 0
    if algorithm == "PRIORITY_AGING":
        results, engine_used = run_priority_aging(jobs, aging_interval)
        algorithm_label = "Priority + Aging"
        notes = f"Non-preemptive priority scheduling with aging every {aging_interval} simulation minutes. Simulation does not resolve tickets."
    elif algorithm == "ROUND_ROBIN":
        results, engine_used, context_switches = run_round_robin(jobs, quantum, context_switch_overhead)
        algorithm_label = "Round Robin"
        notes = f"Preemptive Round Robin simulation; quantum={quantum} simulation minutes; context-switch overhead={context_switch_overhead} minutes. Execution segments are stored independently. Simulation does not resolve tickets."
    else:
        results, engine_used = run_fcfs(jobs)
        algorithm_label = "FCFS"
        notes = "Single-server, non-preemptive FCFS simulation. Simulation completion does not resolve real tickets."
    jobs_by_id = {int(job["ticket_id"]): job for job in jobs}
    if algorithm == "ROUND_ROBIN":
        for result in results:
            arrival_dt = add_work_minutes(anchor, int(result["arrival_time"]))
            mapped_segments = []
            for segment in result.get("segments", []):
                mapped_segments.extend(map_work_interval(anchor, segment["start_time"], segment["end_time"]))
            result["segments"] = mapped_segments
            if not mapped_segments:
                continue
            start_dt = anchor + timedelta(minutes=mapped_segments[0]["start_time"])
            completion_dt = anchor + timedelta(minutes=mapped_segments[-1]["end_time"])
            result["arrival_time"] = wall_offset(anchor, arrival_dt)
            result["start_time"] = mapped_segments[0]["start_time"]
            result["completion_time"] = mapped_segments[-1]["end_time"]
            result["waiting_time"] = max(0, work_minutes_between(arrival_dt, completion_dt) - int(result["service_time"]))
            result["response_time"] = work_minutes_between(arrival_dt, start_dt)
            result["turnaround_time"] = work_minutes_between(arrival_dt, completion_dt)
    else:
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
            result["segments"] = [{"start_time": result["start_time"], "end_time": result["completion_time"]}]
            cursor_time = completion_dt
    waits = [item["waiting_time"] for item in results]
    responses = [item["response_time"] for item in results]
    turnarounds = [item["turnaround_time"] for item in results]
    elapsed_offset = max((item["completion_time"] for item in results), default=0)
    elapsed_wall_end = anchor + timedelta(minutes=elapsed_offset)
    elapsed = work_minutes_between(anchor, elapsed_wall_end)
    busy = sum(item["service_time"] for item in results)
    if algorithm == "ROUND_ROBIN":
        # Context-switch overhead consumes simulated CPU time as well.
        busy += context_switches * context_switch_overhead
    throughput = round(len(results) / elapsed, 4) if elapsed > 0 else 0.0
    utilization = round(100.0 * busy / elapsed, 2) if elapsed > 0 else 0.0
    finished = datetime.now()
    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO scheduling_runs
               (algorithm, engine_used, started_at, completed_at, simulation_anchor_at, ticket_count,
                avg_waiting_time, avg_response_time, avg_turnaround_time, throughput, utilization_percent, notes,
                context_switches, time_quantum, context_switch_overhead)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (algorithm_label, engine_used, anchor.isoformat(timespec="seconds"), finished.isoformat(timespec="seconds"),
             anchor.isoformat(timespec="seconds"), len(results), round(sum(waits)/len(waits), 2),
             round(sum(responses)/len(responses), 2), round(sum(turnarounds)/len(turnarounds), 2),
             throughput, utilization, notes, context_switches, quantum if algorithm == "ROUND_ROBIN" else None, context_switch_overhead if algorithm == "ROUND_ROBIN" else 0)
        )
        run_id = cursor.lastrowid
        for result in results:
            result_cursor = conn.execute(
                """INSERT INTO scheduling_results
                   (run_id, ticket_id, queue_order, arrival_time, service_time, start_time, completion_time,
                    waiting_time, turnaround_time, response_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, result["ticket_id"], result["queue_order"], result["arrival_time"], result["service_time"],
                 result["start_time"], result["completion_time"], result["waiting_time"], result["turnaround_time"], result["response_time"])
            )
            estimated_completion = anchor + timedelta(minutes=result["completion_time"])
            segments = result.get("segments") or [{"start_time": result["start_time"], "end_time": result["completion_time"]}]
            for segment_number, segment in enumerate(segments, 1):
                conn.execute("INSERT INTO scheduling_segments (result_id,segment_number,start_time,end_time) VALUES (?,?,?,?)",
                             (result_cursor.lastrowid, segment_number, segment["start_time"], segment["end_time"]))
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
@admin_required
def admin_run_fcfs():
    return run_scheduler("FCFS")


@app.post("/admin/run-priority-aging")
@admin_required
def admin_run_priority_aging():
    return run_scheduler("PRIORITY_AGING")


@app.post("/admin/run-round-robin")
@admin_required
def admin_run_round_robin():
    try:
        quantum = parse_duration_input(request.form.get("quantum", "00:04"), default=4)
        overhead = parse_duration_input(request.form.get("context_switch_overhead", "00:00"), default=0)
        if not 1 <= quantum <= 240 or not 0 <= overhead <= 30:
            raise ValueError("Time quantum must be 00:01–04:00 and switch overhead 00:00–00:30.")
        return run_scheduler("ROUND_ROBIN", quantum=quantum, overhead=overhead)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_dashboard") + "#scheduler")


def run_scheduler(algorithm: str, quantum: int = 4, overhead: int = 0):
    try:
        run_info = perform_scheduling_run(algorithm, quantum=quantum, context_switch_overhead=overhead)
        if not run_info:
            flash("There are no READY tickets to schedule. Add a ticket or reset the demo data.", "error")
        else:
            flash(f"{run_info['algorithm']} finished for {run_info['ticket_count']} READY tickets using {run_info['engine_used']}. Results saved; tickets remain READY until a technician changes their status.", "success")
    except Exception as exc:
        app.logger.exception("Scheduler failed")
        flash(f"Scheduling could not run: {exc}", "error")
    return redirect(url_for("admin_dashboard") + "#scheduler")


@app.post("/admin/reset-demo")
@admin_required
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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        supplied = request.form.get("password", "")
        expected = os.environ.get("ADMIN_PASSWORD", "admin123")
        if supplied and supplied == expected:
            session.clear()
            session["admin_authenticated"] = True
            session.permanent = True
            flash("Signed in to the administrator workspace.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("The administrator password was not accepted.", "error")
    return render_template("login.html", login_type="Administrator", action=url_for("admin_login"))


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.post("/admin/organizations")
@admin_required
def admin_create_organization():
    name = (request.form.get("organization_name") or "").strip()
    email = (request.form.get("contact_email") or "").strip().lower()
    if not name or len(name) > 140 or len(email) > 190 or (email and ("@" not in email or "." not in email.rsplit("@", 1)[-1])):
        flash("Enter a valid organization name and optional contact email.", "error")
        return redirect(url_for("admin_dashboard") + "#organizations")
    try:
        get_db().execute("INSERT INTO organizations (organization_name,contact_email,created_at) VALUES (?,?,?)", (name,email or None,timestamp()))
        get_db().commit()
        flash(f"Organization '{name}' was added.", "success")
    except Exception:
        get_db().rollback()
        flash("That organization could not be created. The name may already exist.", "error")
    return redirect(url_for("admin_dashboard") + "#organizations")


@app.post("/admin/organizations/<int:organization_id>/toggle")
@admin_required
def admin_toggle_organization(organization_id: int):
    row = fetch_one("SELECT is_active FROM organizations WHERE organization_id=?", (organization_id,))
    if not row:
        flash("Organization not found.", "error")
    else:
        get_db().execute("UPDATE organizations SET is_active=? WHERE organization_id=?", (0 if row["is_active"] else 1, organization_id))
        get_db().commit()
        flash("Organization access was updated.", "success")
    return redirect(url_for("admin_dashboard") + "#organizations")


@app.post("/admin/technicians")
@admin_required
def admin_create_technician():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip()
    password = request.form.get("password") or ""
    if not name or not email or "@" not in email or len(name) > 100 or len(email) > 190 or len(phone) > 30 or len(password) < 8:
        flash("Provide a valid name/email and a password of at least 8 characters.", "error")
        return redirect(url_for("admin_dashboard") + "#technicians")
    try:
        now = timestamp()
        get_db().execute("INSERT INTO technicians (name,email,phone,password_hash,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         (name,email,phone or None,generate_password_hash(password),now,now))
        get_db().commit()
        flash(f"Technician account created for {name}.", "success")
    except Exception:
        get_db().rollback()
        flash("Technician could not be created. Check whether the email is already registered.", "error")
    return redirect(url_for("admin_dashboard") + "#technicians")


@app.post("/admin/technicians/<int:technician_id>/availability")
@admin_required
def admin_update_technician_availability(technician_id: int):
    availability = request.form.get("availability", "AVAILABLE")
    if availability not in {"AVAILABLE", "BUSY", "UNAVAILABLE"}:
        flash("Choose a valid availability status.", "error")
    else:
        get_db().execute("UPDATE technicians SET availability=?,updated_at=? WHERE technician_id=?", (availability,timestamp(),technician_id))
        get_db().commit()
        flash("Technician availability updated.", "success")
    return redirect(url_for("admin_dashboard") + "#technicians")


@app.post("/admin/technicians/<int:technician_id>/toggle")
@admin_required
def admin_toggle_technician(technician_id: int):
    row = fetch_one("SELECT is_active FROM technicians WHERE technician_id=?", (technician_id,))
    if row:
        get_db().execute("UPDATE technicians SET is_active=?,updated_at=? WHERE technician_id=?", (0 if row["is_active"] else 1,timestamp(),technician_id))
        get_db().commit()
        flash("Technician account status updated.", "success")
    else:
        flash("Technician not found.", "error")
    return redirect(url_for("admin_dashboard") + "#technicians")


@app.post("/admin/tickets/<int:ticket_id>/assign")
@admin_required
def admin_assign_ticket(ticket_id: int):
    try:
        technician_id = int(request.form.get("technician_id", "0"))
        ticket = fetch_one("SELECT status,assignment_version FROM tickets WHERE ticket_id=?", (ticket_id,))
        technician = fetch_one("SELECT technician_id,name FROM technicians WHERE technician_id=? AND is_active=1 AND availability!='UNAVAILABLE'", (technician_id,))
        if not ticket or ticket["status"] in {"RESOLVED", "CLOSED"} or not technician:
            raise ValueError("Choose an active technician and a ticket that is not closed.")
        conn = get_db()
        # Optimistic version check makes competing claims mutually exclusive.
        changed = conn.execute("UPDATE tickets SET status='ASSIGNED',assignment_version=assignment_version+1,updated_at=? WHERE ticket_id=? AND assignment_version=? AND status NOT IN ('RESOLVED','CLOSED')",
                               (timestamp(),ticket_id,ticket["assignment_version"]))
        if changed.rowcount != 1:
            conn.rollback()
            raise ValueError("Another administrator updated this ticket. Refresh and try again.")
        conn.execute("UPDATE ticket_assignments SET is_active=0,released_at=? WHERE ticket_id=? AND is_active=1", (timestamp(),ticket_id))
        conn.execute("INSERT INTO ticket_assignments (ticket_id,technician_id,assigned_by,assigned_at,is_active) VALUES (?,?,?,?,1)",
                     (ticket_id,technician_id,"ADMIN",timestamp()))
        conn.execute("INSERT INTO ticket_history (ticket_id,old_status,new_status,changed_by,changed_at,note) VALUES (?,?,?,?,?,?)",
                     (ticket_id,ticket["status"],"ASSIGNED","ADMIN",timestamp(),f"Assigned to {technician['name']}"))
        conn.commit()
        flash(f"{ticket_code(ticket_id)} assigned to {technician['name']}.", "success")
    except (ValueError, TypeError) as exc:
        flash(str(exc), "error")
    except Exception:
        get_db().rollback()
        app.logger.exception("Ticket assignment failed")
        flash("Assignment failed. No partial assignment was saved.", "error")
    return redirect(url_for("admin_dashboard") + "#ticket-queue")


def banker_safety_check(request_technician: int, request_resource: int, request_quantity: int, proposed_max: int) -> tuple[bool, str]:
    resources = fetch_all("SELECT resource_id,total_quantity FROM resources WHERE is_active=1 ORDER BY resource_id")
    techs = fetch_all("SELECT technician_id FROM technicians WHERE is_active=1 ORDER BY technician_id")
    resource_ids = [int(row["resource_id"]) for row in resources]
    tech_ids = [int(row["technician_id"]) for row in techs]
    if request_resource not in resource_ids or request_technician not in tech_ids:
        return False, "The selected resource or technician is unavailable."
    totals = {int(r["resource_id"]): int(r["total_quantity"]) for r in resources}
    allocation = {tid: {rid: 0 for rid in resource_ids} for tid in tech_ids}
    maximum = {tid: {rid: 0 for rid in resource_ids} for tid in tech_ids}
    for row in fetch_all("SELECT technician_id,resource_id,quantity FROM resource_allocations WHERE status='ALLOCATED'"):
        tid, rid = int(row["technician_id"]), int(row["resource_id"])
        if tid in allocation and rid in totals: allocation[tid][rid] += int(row["quantity"])
    for row in fetch_all("SELECT technician_id,resource_id,max_quantity FROM resource_claims"):
        tid, rid = int(row["technician_id"]), int(row["resource_id"])
        if tid in maximum and rid in totals: maximum[tid][rid] = int(row["max_quantity"])
    maximum[request_technician][request_resource] = int(proposed_max)
    if request_quantity > proposed_max - allocation[request_technician][request_resource]:
        return False, "Requested quantity exceeds this technician's declared maximum claim."
    available = {rid: totals[rid] - sum(allocation[tid][rid] for tid in tech_ids) for rid in resource_ids}
    if request_quantity > available[request_resource]:
        return False, "Not enough unallocated units are currently available."
    allocation[request_technician][request_resource] += request_quantity
    available[request_resource] -= request_quantity
    finish = {tid: False for tid in tech_ids}
    sequence = []
    while True:
        progressed = False
        for tid in tech_ids:
            if finish[tid]: continue
            need = {rid: maximum[tid][rid] - allocation[tid][rid] for rid in resource_ids}
            if all(value >= 0 and value <= available[rid] for rid, value in need.items()):
                for rid in resource_ids: available[rid] += allocation[tid][rid]
                finish[tid] = True
                sequence.append(tid)
                progressed = True
        if not progressed: break
    if all(finish.values()):
        return True, "Safe state. Safe sequence: " + " → ".join(f"T{tid}" for tid in sequence)
    return False, "Unsafe state detected by Banker's Algorithm; allocation was rejected. Check maximum claims and current allocations."


@app.post("/admin/resources")
@admin_required
def admin_create_resource():
    name = (request.form.get("resource_name") or "").strip()
    description = (request.form.get("description") or "").strip()
    try:
        quantity = int(request.form.get("total_quantity", "0"))
        org_raw = request.form.get("organization_id", "")
        org_id = int(org_raw) if org_raw else None
        if not name or len(name) > 140 or len(description) > 500 or quantity < 0:
            raise ValueError("Enter a resource name and a non-negative quantity.")
        get_db().execute("INSERT INTO resources (organization_id,resource_name,description,total_quantity,created_at) VALUES (?,?,?,?,?)",
                         (org_id,name,description or None,quantity,timestamp()))
        get_db().commit()
        flash("Resource added to the inventory.", "success")
    except (ValueError, TypeError) as exc:
        flash(str(exc), "error")
    except Exception:
        get_db().rollback()
        flash("Resource could not be added.", "error")
    return redirect(url_for("admin_dashboard") + "#resources")


@app.post("/admin/resources/allocate")
@admin_required
def admin_allocate_resource():
    try:
        tid = int(request.form.get("technician_id", "0"))
        rid = int(request.form.get("resource_id", "0"))
        qty = int(request.form.get("quantity", "0"))
        max_claim = int(request.form.get("max_claim", "0"))
        ticket_raw = request.form.get("ticket_id", "")
        ticket_id = int(ticket_raw) if ticket_raw else None
        if qty <= 0 or max_claim < qty:
            raise ValueError("Quantity must be positive and maximum claim must be at least the requested quantity.")
        conn = get_db()
        if DB_MODE == "sqlite":
            # Serialize the read-check-write sequence so concurrent requests cannot
            # both pass Banker's safety checks against the same available units.
            conn.execute("BEGIN IMMEDIATE")
            resource = fetch_one("SELECT organization_id FROM resources WHERE resource_id=? AND is_active=1", (rid,))
        else:
            # Banker evaluates the full resource vector, so lock all active resource
            # rows in a stable order until the proposed allocation is committed.
            conn.execute("SELECT resource_id FROM resources WHERE is_active=1 ORDER BY resource_id FOR UPDATE").fetchall()
            resource = fetch_one("SELECT organization_id FROM resources WHERE resource_id=? AND is_active=1", (rid,))
        if not resource: raise ValueError("Select an active resource.")
        if ticket_id is not None:
            ticket_org = fetch_one("SELECT organization_id FROM tickets WHERE ticket_id=?", (ticket_id,))
            if not ticket_org: raise ValueError("Linked ticket does not exist.")
            if resource["organization_id"] is not None and int(resource["organization_id"]) != int(ticket_org["organization_id"]):
                raise ValueError("This resource belongs to a different organization.")
        safe, detail = banker_safety_check(tid, rid, qty, max_claim)
        if not safe: raise ValueError(detail)
        # Update/insert the declared maximum claim in a DB-mode-neutral way.
        claim = fetch_one("SELECT claim_id FROM resource_claims WHERE technician_id=? AND resource_id=?", (tid,rid))
        if claim:
            conn.execute("UPDATE resource_claims SET max_quantity=? WHERE claim_id=?", (max_claim,claim["claim_id"]))
        else:
            conn.execute("INSERT INTO resource_claims (technician_id,resource_id,max_quantity) VALUES (?,?,?)", (tid,rid,max_claim))
        conn.execute("INSERT INTO resource_allocations (ticket_id,technician_id,resource_id,quantity,status,allocated_at) VALUES (?,?,?,?,'ALLOCATED',?)",
                     (ticket_id,tid,rid,qty,timestamp()))
        conn.commit()
        flash("Resource allocated. " + detail, "success")
    except (ValueError, TypeError) as exc:
        get_db().rollback()
        flash(str(exc), "error")
    except Exception:
        get_db().rollback()
        app.logger.exception("Resource allocation failed")
        flash("Resource allocation failed; no partial changes were saved.", "error")
    return redirect(url_for("admin_dashboard") + "#resources")


@app.post("/admin/resources/<int:allocation_id>/release")
@admin_required
def admin_release_resource(allocation_id: int):
    conn = get_db()
    try:
        if DB_MODE == "sqlite":
            conn.execute("BEGIN IMMEDIATE")
        else:
            conn.execute("SELECT resource_id FROM resources WHERE is_active=1 ORDER BY resource_id FOR UPDATE").fetchall()
        row = fetch_one("SELECT allocation_id FROM resource_allocations WHERE allocation_id=? AND status='ALLOCATED'", (allocation_id,))
        if row:
            changed = conn.execute("UPDATE resource_allocations SET status='RELEASED',released_at=? WHERE allocation_id=? AND status='ALLOCATED'", (timestamp(),allocation_id))
            if changed.rowcount != 1:
                conn.rollback()
                flash("This allocation was already released. Refresh the resource history.", "error")
            else:
                conn.commit()
                flash("Resource released and made available again.", "success")
        else:
            conn.rollback()
            flash("Active allocation not found.", "error")
    except Exception:
        conn.rollback()
        app.logger.exception("Resource release failed")
        flash("The resource allocation could not be released.", "error")
    return redirect(url_for("admin_dashboard") + "#resources")


@app.route("/admin/login-technician", methods=["GET", "POST"])
def technician_login():
    if session.get("technician_id"):
        return redirect(url_for("technician_dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        tech = fetch_one("SELECT technician_id,name,password_hash FROM technicians WHERE email=? AND is_active=1", (email,))
        if tech and tech.get("password_hash") and check_password_hash(tech["password_hash"], password):
            session.clear()
            session["technician_id"] = int(tech["technician_id"])
            session["technician_name"] = tech["name"]
            session.permanent = True
            return redirect(url_for("technician_dashboard"))
        flash("Invalid technician credentials or inactive account.", "error")
    return render_template("login.html", login_type="Technician", action=url_for("technician_login"))


@app.post("/technician/logout")
@technician_required
def technician_logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/technician")
@technician_required
def technician_dashboard():
    tid = int(session["technician_id"])
    active_tech = fetch_one("SELECT technician_id FROM technicians WHERE technician_id=? AND is_active=1", (tid,))
    if not active_tech:
        session.clear()
        flash("This technician account is inactive.", "error")
        return redirect(url_for("technician_login"))
    tickets = fetch_all("""SELECT t.ticket_id,t.title,t.description,t.status,t.priority,t.created_at,o.organization_name,c.category_name,
        u.name AS requester_name FROM ticket_assignments a JOIN tickets t ON t.ticket_id=a.ticket_id
        JOIN users u ON u.user_id=t.user_id JOIN categories c ON c.category_id=t.category_id
        LEFT JOIN organizations o ON o.organization_id=t.organization_id
        WHERE a.technician_id=? AND a.is_active=1 AND t.status NOT IN ('RESOLVED','CLOSED') ORDER BY t.priority,t.created_at""", (tid,))
    tech = fetch_one("SELECT name,email,availability FROM technicians WHERE technician_id=?", (tid,))
    return render_template("technician.html", tickets=tickets, technician=tech)


@app.post("/technician/tickets/<int:ticket_id>/status")
@technician_required
def technician_update_ticket(ticket_id: int):
    tid = int(session["technician_id"])
    if not fetch_one("SELECT technician_id FROM technicians WHERE technician_id=? AND is_active=1", (tid,)):
        session.clear()
        flash("This technician account is inactive.", "error")
        return redirect(url_for("technician_login"))
    new_status = request.form.get("status", "")
    note = (request.form.get("note") or "").strip()[:1000]
    if new_status not in {"IN_PROGRESS", "WAITING", "RESOLVED"}:
        flash("Choose a valid ticket status.", "error")
        return redirect(url_for("technician_dashboard"))
    conn = get_db()
    assignment = fetch_one("SELECT assignment_id FROM ticket_assignments WHERE ticket_id=? AND technician_id=? AND is_active=1", (ticket_id,tid))
    current = fetch_one("SELECT status FROM tickets WHERE ticket_id=?", (ticket_id,))
    allowed = {"ASSIGNED": {"IN_PROGRESS", "WAITING"}, "IN_PROGRESS": {"WAITING", "RESOLVED"}, "WAITING": {"IN_PROGRESS", "RESOLVED"}}
    if not assignment or not current or new_status not in allowed.get(current["status"], set()):
        flash("This ticket is not assigned to you or the requested status transition is not allowed.", "error")
        return redirect(url_for("technician_dashboard"))
    now = timestamp()
    changed = conn.execute("UPDATE tickets SET status=?,resolved_at=?,resolution_notes=?,updated_at=? WHERE ticket_id=? AND status=?",
                           (new_status,now if new_status=="RESOLVED" else None,note or None,now,ticket_id,current["status"]))
    if changed.rowcount != 1:
        conn.rollback()
        flash("Another update changed this ticket. Refresh and try again.", "error")
        return redirect(url_for("technician_dashboard"))
    conn.execute("INSERT INTO ticket_history (ticket_id,old_status,new_status,changed_by,changed_at,note) VALUES (?,?,?,?,?,?)",
                 (ticket_id,current["status"],new_status,session.get("technician_name","TECHNICIAN"),now,note or "Status updated by assigned technician."))
    conn.commit()
    flash(f"{ticket_code(ticket_id)} updated to {new_status.replace('_',' ')}.", "success")
    return redirect(url_for("technician_dashboard"))


@app.post("/rate-ticket")
def rate_ticket():
    raw_id = request.form.get("ticket_id", "")
    email = (request.form.get("email") or "").strip().lower()
    ticket_id = parse_ticket_code(raw_id)
    try:
        service_rating = int(request.form.get("service_rating", "0"))
        technician_rating_raw = request.form.get("technician_rating", "")
        technician_rating = int(technician_rating_raw) if technician_rating_raw else None
    except ValueError:
        flash("Choose a rating between 1 and 5.", "error")
        return redirect(url_for("track_lookup"))
    feedback = (request.form.get("feedback") or "").strip()[:1000]
    ticket = fetch_ticket(ticket_id) if ticket_id else None
    if not ticket or ticket["status"] not in {"RESOLVED", "CLOSED"} or email != str(ticket["requester_email"]).lower():
        flash("The rating could not be matched to a resolved ticket and its requester email.", "error")
        return redirect(url_for("track_lookup"))
    if service_rating not in range(1,6) or (technician_rating is not None and technician_rating not in range(1,6)):
        flash("Service rating is required and must be between 1 and 5.", "error")
        session["ticket_lookup"] = {"ticket_id": ticket_code(ticket_id), "email": email}
        return redirect(url_for("track_lookup"))
    existing = fetch_one("SELECT rating_id FROM service_ratings WHERE ticket_id=?", (ticket_id,))
    if existing:
        flash("A service rating has already been submitted for this ticket.", "error")
        session["ticket_lookup"] = {"ticket_id": ticket_code(ticket_id), "email": email}
        return redirect(url_for("track_lookup"))
    assignment = fetch_one("SELECT technician_id FROM ticket_assignments WHERE ticket_id=? ORDER BY assignment_id DESC LIMIT 1", (ticket_id,))
    if technician_rating is not None and not assignment:
        flash("This ticket has no assigned technician to rate. Submit the service rating only.", "error")
        session["ticket_lookup"] = {"ticket_id": ticket_code(ticket_id), "email": email}
        return redirect(url_for("track_lookup"))
    conn = get_db()
    try:
        now = timestamp()
        conn.execute("INSERT INTO service_ratings (ticket_id,category_id,requester_email,rating,feedback,created_at) VALUES (?,?,?,?,?,?)",
                     (ticket_id,ticket["category_id"],email,service_rating,feedback or None,now))
        if technician_rating is not None and assignment:
            conn.execute("INSERT INTO technician_ratings (ticket_id,technician_id,requester_email,rating,feedback,created_at) VALUES (?,?,?,?,?,?)",
                         (ticket_id,assignment["technician_id"],email,technician_rating,feedback or None,now))
        conn.commit()
        flash("Thank you. Your service feedback has been recorded.", "success")
    except Exception:
        conn.rollback()
        flash("A rating could not be saved. It may already have been submitted.", "error")
    session["ticket_lookup"] = {"ticket_id": ticket_code(ticket_id), "email": email}
    return redirect(url_for("track_lookup"))


@app.route("/services")
def service_performance():
    ratings = fetch_all("SELECT category_name,ROUND(avg_rating,2) AS average_rating,rating_count AS review_count FROM v_service_category_performance ORDER BY category_name")
    overall = fetch_one("SELECT ROUND(AVG(rating),2) AS average_rating,COUNT(*) AS review_count FROM service_ratings") or {"average_rating": None,"review_count":0}
    return render_template("services.html", ratings=ratings, overall=overall)


def build_comparison():
    jobs = fetch_all("SELECT ticket_id,arrival_offset,estimated_service_minutes,priority FROM tickets WHERE status='READY' ORDER BY arrival_offset,ticket_id")
    if not jobs:
        return []
    algorithms = []
    for label, runner in [("FCFS", lambda: (run_fcfs(jobs)[0], 0)),
                          ("Priority + Aging", lambda: (run_priority_aging(jobs, 5)[0], 0)),
                          ("Round Robin (q=4)", lambda: (lambda out: (out[0],out[2]))(run_round_robin(jobs,4,0)))]:
        results, switches = runner()
        waits = [r["waiting_time"] for r in results]
        responses = [r["response_time"] for r in results]
        turns = [r["turnaround_time"] for r in results]
        elapsed = max((r["completion_time"] for r in results), default=0)
        busy = sum(r["service_time"] for r in results)
        avg_wait = round(sum(waits)/len(waits),2)
        avg_response = round(sum(responses)/len(responses),2)
        avg_turnaround = round(sum(turns)/len(turns),2)
        algorithms.append({"name":label,"waiting":avg_wait,"response":avg_response,"turnaround":avg_turnaround,
                           "waiting_label":format_duration(avg_wait),"response_label":format_duration(avg_response),
                           "turnaround_label":format_duration(avg_turnaround),
                           "throughput":round(len(results)/elapsed,4) if elapsed else 0,
                           "utilization":round(100*busy/elapsed,2) if elapsed else 0,"context_switches":switches})
    return algorithms


with app.app_context():
    init_db()
    insert_demo_data(force=False)


if __name__ == "__main__":
    print(f"Help Desk running with {DB_MODE} database mode.")
    print("Open http://127.0.0.1:5000")
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
