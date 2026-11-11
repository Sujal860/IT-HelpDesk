from __future__ import annotations

import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DB_MODE = os.environ.get("DB_MODE", "sqlite").strip().lower()
if DB_MODE not in {"sqlite", "mysql"}:
    raise RuntimeError("DB_MODE must be either sqlite or mysql")
SQLITE_PATH = os.environ.get("SQLITE_PATH", str(ROOT / "helpdesk_demo.db"))

try:
    from flask import g
except ImportError:  # pragma: no cover
    g = None


class MySQLConnectionWrapper:
    """Small adapter so application code can use the same execute API as SQLite."""
    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement, params=()):
        from datetime import datetime
        cursor = self._connection.cursor()
        converted = []
        for value in params:
            if isinstance(value, str) and len(value) == 19 and value[10] == "T":
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    pass
            converted.append(value)
        cursor.execute(statement.replace("?", "%s"), tuple(converted))
        return cursor

    def cursor(self):
        return self._connection.cursor()

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


def _mysql_connect():
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:
        raise RuntimeError("MySQL mode needs PyMySQL. Run: pip install PyMySQL") from exc
    raw = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "helpdesk_db"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    return MySQLConnectionWrapper(raw)


def get_db():
    if g is None:
        raise RuntimeError("Flask application context is required")
    if "helpdesk_db_conn" not in g:
        if DB_MODE == "mysql":
            g.helpdesk_db_conn = _mysql_connect()
        else:
            conn = sqlite3.connect(SQLITE_PATH, timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            g.helpdesk_db_conn = conn
    return g.helpdesk_db_conn


def close_db():
    if g is not None and hasattr(g, "helpdesk_db_conn"):
        g.helpdesk_db_conn.close()
        del g.helpdesk_db_conn


def _sql(statement: str) -> str:
    return statement.replace("?", "%s") if DB_MODE == "mysql" else statement


def execute(statement: str, params: Iterable[Any] = ()):
    conn = get_db()
    if DB_MODE == "mysql":
        return conn.execute(statement, tuple(params))
    return conn.execute(statement, tuple(params))


def fetch_one(statement: str, params: Iterable[Any] = ()):
    cursor = execute(statement, params)
    row = cursor.fetchone()
    return dict(row) if row is not None and not isinstance(row, dict) else row


def fetch_all(statement: str, params: Iterable[Any] = ()):
    cursor = execute(statement, params)
    rows = cursor.fetchall()
    return [dict(row) if not isinstance(row, dict) else row for row in rows]


def init_db():
    conn = get_db()
    if DB_MODE == "mysql":
        statements = [
            """CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(190) NOT NULL UNIQUE,
                role VARCHAR(20) NOT NULL DEFAULT 'USER',
                created_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS categories (
                category_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                category_name VARCHAR(80) NOT NULL UNIQUE,
                description VARCHAR(255) NOT NULL,
                default_priority INT NOT NULL DEFAULT 3,
                default_service_minutes INT NOT NULL DEFAULT 30
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS tickets (
                ticket_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT NOT NULL,
                category_id BIGINT NOT NULL,
                title VARCHAR(160) NOT NULL,
                description TEXT NOT NULL,
                location_or_asset VARCHAR(180) NULL,
                priority INT NOT NULL DEFAULT 3,
                status VARCHAR(24) NOT NULL DEFAULT 'READY',
                estimated_service_minutes INT NOT NULL DEFAULT 30,
                arrival_offset INT NOT NULL DEFAULT 0,
                estimated_wait_minutes INT NULL,
                estimated_completion_at DATETIME NULL,
                confirmed_target_at DATETIME NULL,
                actual_started_at DATETIME NULL,
                resolved_at DATETIME NULL,
                resolution_notes TEXT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT fk_ticket_user FOREIGN KEY (user_id) REFERENCES users(user_id),
                CONSTRAINT fk_ticket_category FOREIGN KEY (category_id) REFERENCES categories(category_id),
                INDEX idx_ticket_status_arrival (status, arrival_offset),
                INDEX idx_ticket_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS ticket_history (
                history_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                ticket_id BIGINT NOT NULL,
                old_status VARCHAR(24) NULL,
                new_status VARCHAR(24) NOT NULL,
                changed_by VARCHAR(100) NOT NULL,
                changed_at DATETIME NOT NULL,
                note VARCHAR(1000) NULL,
                CONSTRAINT fk_history_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                INDEX idx_history_ticket_time (ticket_id, changed_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS scheduling_runs (
                run_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                algorithm VARCHAR(32) NOT NULL,
                engine_used VARCHAR(255) NOT NULL,
                started_at DATETIME NOT NULL,
                completed_at DATETIME NOT NULL,
                simulation_anchor_at DATETIME NOT NULL,
                ticket_count INT NOT NULL,
                avg_waiting_time DECIMAL(12,2) NOT NULL,
                avg_response_time DECIMAL(12,2) NOT NULL,
                avg_turnaround_time DECIMAL(12,2) NOT NULL,
                throughput DECIMAL(12,4) NOT NULL,
                utilization_percent DECIMAL(8,2) NOT NULL,
                notes VARCHAR(1000) NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS scheduling_results (
                result_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                run_id BIGINT NOT NULL,
                ticket_id BIGINT NOT NULL,
                queue_order INT NOT NULL,
                arrival_time INT NOT NULL,
                service_time INT NOT NULL,
                start_time INT NOT NULL,
                completion_time INT NOT NULL,
                waiting_time INT NOT NULL,
                turnaround_time INT NOT NULL,
                response_time INT NOT NULL,
                CONSTRAINT fk_result_run FOREIGN KEY (run_id) REFERENCES scheduling_runs(run_id) ON DELETE CASCADE,
                CONSTRAINT fk_result_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                INDEX idx_result_run_order (run_id, queue_order),
                INDEX idx_result_ticket (ticket_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        ]
        try:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'USER',
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS categories (
                category_id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                default_priority INTEGER NOT NULL DEFAULT 3,
                default_service_minutes INTEGER NOT NULL DEFAULT 30
            )""",
            """CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                category_id INTEGER NOT NULL REFERENCES categories(category_id),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                location_or_asset TEXT,
                priority INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'READY',
                estimated_service_minutes INTEGER NOT NULL DEFAULT 30,
                arrival_offset INTEGER NOT NULL DEFAULT 0,
                estimated_wait_minutes INTEGER,
                estimated_completion_at TEXT,
                confirmed_target_at TEXT,
                actual_started_at TEXT,
                resolved_at TEXT,
                resolution_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS ticket_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                old_status TEXT,
                new_status TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                note TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS scheduling_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                algorithm TEXT NOT NULL,
                engine_used TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                simulation_anchor_at TEXT NOT NULL,
                ticket_count INTEGER NOT NULL,
                avg_waiting_time REAL NOT NULL,
                avg_response_time REAL NOT NULL,
                avg_turnaround_time REAL NOT NULL,
                throughput REAL NOT NULL,
                utilization_percent REAL NOT NULL,
                notes TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS scheduling_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES scheduling_runs(run_id) ON DELETE CASCADE,
                ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                queue_order INTEGER NOT NULL,
                arrival_time INTEGER NOT NULL,
                service_time INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                completion_time INTEGER NOT NULL,
                waiting_time INTEGER NOT NULL,
                turnaround_time INTEGER NOT NULL,
                response_time INTEGER NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_ticket_status_arrival ON tickets(status, arrival_offset)",
            "CREATE INDEX IF NOT EXISTS idx_ticket_created ON tickets(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_history_ticket_time ON ticket_history(ticket_id, changed_at)",
            "CREATE INDEX IF NOT EXISTS idx_result_run_order ON scheduling_results(run_id, queue_order)",
            "CREATE INDEX IF NOT EXISTS idx_result_ticket ON scheduling_results(ticket_id)",
        ]
        for statement in statements:
            conn.execute(statement)
        conn.commit()

    from phase3_schema import init_phase3_schema
    init_phase3_schema(conn, DB_MODE)
    seed_categories()


def seed_categories():
    categories = [
        ("Network", "Wi-Fi, LAN, or internet connectivity problems", 1, 25),
        ("Server / Application", "Shared server, portal, or application outage", 1, 45),
        ("Account / Login", "Password, account access, or authentication issue", 2, 15),
        ("Printer / Peripheral", "Printer, scanner, keyboard, or mouse issue", 3, 20),
        ("Software Installation", "Install, update, or configure approved software", 3, 30),
        ("Hardware", "Desktop, laptop, monitor, or component issue", 2, 40),
        ("Classroom AV", "Projector, display, or classroom audio/visual issue", 2, 25),
        ("General Request", "Routine IT help or information request", 4, 20),
        ("System Maintenance", "Preventive maintenance, updates, and system health checks", 3, 35),
        ("Cybersecurity Support", "Endpoint security, suspicious activity, and access protection", 1, 45),
    ]
    conn = get_db()
    for row in categories:
        if DB_MODE == "mysql":
            conn.execute(
                "INSERT IGNORE INTO categories (category_name, description, default_priority, default_service_minutes) VALUES (?, ?, ?, ?)", row
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO categories (category_name, description, default_priority, default_service_minutes) VALUES (?, ?, ?, ?)", row
            )
    conn.commit()


def _now_str(offset_days: int = 0, offset_hours: int = 0) -> str:
    return (datetime.now() - timedelta(days=offset_days, hours=offset_hours)).isoformat(timespec="seconds")


DEMO_TICKETS = [
    ("Lab Wi-Fi disconnects every few minutes", "Students in Lab C lose connectivity repeatedly during practical sessions.", "CSE Lab C", "Network", 1, "READY", 10, 0),
    ("Student portal returns a 500 error", "The results portal displays an internal server error for multiple users.", "Student Portal", "Server / Application", 4, "READY", 5, 1),
    ("Faculty account locked after login attempts", "Faculty member cannot access the learning portal after several failed attempts.", "Faculty Portal", "Account / Login", 2, "READY", 15, 2),
    ("Printer queue stuck in Block B", "Jobs remain pending and the printer does not produce output.", "Block B, Room 204", "Printer / Peripheral", 3, "READY", 20, 3),
    ("Install approved C++ compiler in lab", "Several lab PCs need the approved compiler and environment variables configured.", "CSE Lab A", "Software Installation", 3, "READY", 35, 4),
    ("Desktop reboots unexpectedly", "A lab desktop reboots under load and needs diagnostics.", "Lab D, PC-18", "Hardware", 2, "READY", 40, 5),
    ("Projector has no HDMI signal", "The lecture hall projector shows no signal from the instructor PC.", "Lecture Hall 2", "Classroom AV", 2, "READY", 25, 6),
    ("Request access to shared drive", "A project team needs read/write access to its approved shared folder.", "Research Lab", "General Request", 4, "READY", 20, 7),
    ("VPN connection fails off campus", "Remote VPN authentication fails despite the correct credentials.", "Remote access", "Network", 2, "READY", 30, 8),
    ("Lab workstation cannot reach the internal application server", "The workstation can reach local services but cannot connect to the shared application server.", "IT Lab", "Server / Application", 2, "READY", 35, 9),
    ("Reset password for library kiosk", "A library kiosk account needs its password reset after a lockout.", "Central Library", "Account / Login", 3, "READY", 15, 10),
    ("Scanner produces blank pages", "The office scanner feeder works but output pages are blank.", "Admin Office", "Printer / Peripheral", 3, "READY", 20, 11),
    ("Install visualization package for Python lab", "Install and verify an approved plotting package on lab machines.", "Data Science Lab", "Software Installation", 3, "READY", 30, 12),
    ("Laptop fan noise and overheating", "Technician should inspect cooling and check for dust accumulation.", "Faculty Cabin 12", "Hardware", 2, "ASSIGNED", 40, 13),
    ("Microphone audio is very low", "Room microphone output is too quiet for a lecture recording.", "Seminar Room", "Classroom AV", 3, "IN_PROGRESS", 25, 14),
    ("Slow internet in administration wing", "Several users report slow access to internal websites.", "Admin Wing", "Network", 2, "READY", 30, 15),
    ("Update browser on placement cell PC", "Update the browser to the supported version and verify placement site access.", "Placement Cell", "Software Installation", 4, "READY", 20, 16),
    ("Mouse not detected on workstation", "The workstation intermittently loses the USB mouse.", "Lab B, PC-09", "Hardware", 4, "RESOLVED", 15, 17),
    ("Email client cannot sync", "Email works in browser but does not synchronize in the desktop client.", "Faculty Cabin 4", "Account / Login", 3, "READY", 25, 18),
    ("Need network port enabled for demo", "A supervised project demo needs an approved network port checked and enabled.", "Project Room 1", "Network", 3, "WAITING", 25, 19),
    ("Student result PDF downloads corrupted", "Downloaded result PDFs are incomplete for several browsers.", "Results Portal", "Server / Application", 2, "READY", 35, 20),
    ("Office workstation printer mapping", "Map the shared office printer to a replacement workstation.", "Office 3", "Printer / Peripheral", 4, "CLOSED", 20, 21),
]


def insert_demo_data(force: bool = False):
    conn = get_db()
    existing = fetch_one("SELECT COUNT(*) AS n FROM tickets")
    if existing and int(existing["n"]) > 0 and not force:
        return
    if force:
        reset_demo_data()
        seed_categories()

    category_rows = fetch_all("SELECT category_id, category_name FROM categories")
    category_map = {row["category_name"]: row["category_id"] for row in category_rows}
    default_org = fetch_one("SELECT organization_id FROM organizations WHERE is_active=1 ORDER BY organization_id LIMIT 1")
    org_id = int(default_org["organization_id"]) if default_org else None
    for i, item in enumerate(DEMO_TICKETS):
        title, description, location, category_name, priority, status, service, arrival = item
        email = f"demo.requester{i+1:02d}@example.edu"
        name = ["Aarav Sharma", "Diya Rawat", "Kabir Joshi", "Ananya Negi", "Vivaan Singh", "Meera Thapa"][i % 6]
        user = fetch_one("SELECT user_id FROM users WHERE email=?", (email,))
        if user:
            user_id = user["user_id"]
        else:
            cursor = conn.execute(
                "INSERT INTO users (name, email, role, created_at, organization_id) VALUES (?, ?, 'USER', ?, ?)",
                (name, email, _now_str(offset_days=i % 5, offset_hours=i % 4), org_id)
            )
            user_id = cursor.lastrowid
        if org_id is not None:
            if DB_MODE == "mysql":
                conn.execute("INSERT IGNORE INTO organization_users (organization_id,user_id,joined_at) VALUES (?,?,?)", (org_id,user_id,_now_str()))
            else:
                conn.execute("INSERT OR IGNORE INTO organization_users (organization_id,user_id,joined_at) VALUES (?,?,?)", (org_id,user_id,_now_str()))
        created = _now_str(offset_days=i % 5, offset_hours=i % 7)
        cursor = conn.execute(
            """INSERT INTO tickets
               (user_id, category_id, organization_id, title, description, location_or_asset, priority, status,
                estimated_service_minutes, arrival_offset, created_at, updated_at,
                resolved_at, resolution_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, category_map[category_name], org_id, title, description, location, priority, status,
             service, arrival, created, created,
             _now_str(offset_days=max(0, i % 3)) if status in ("RESOLVED", "CLOSED") else None,
             "Demo ticket marked complete for dashboard examples." if status in ("RESOLVED", "CLOSED") else None)
        )
        ticket_id = cursor.lastrowid
        note = "Seeded realistic demo ticket."
        conn.execute(
            "INSERT INTO ticket_history (ticket_id, old_status, new_status, changed_by, changed_at, note) VALUES (?, NULL, ?, 'DEMO SEED', ?, ?)",
            (ticket_id, status, created, note)
        )
    conn.commit()


def reset_demo_data():
    conn = get_db()
    conn.execute("DELETE FROM resource_allocations")
    conn.execute("DELETE FROM technician_ratings")
    conn.execute("DELETE FROM service_ratings")
    conn.execute("DELETE FROM ticket_assignments")
    conn.execute("DELETE FROM scheduling_segments")
    conn.execute("DELETE FROM scheduling_results")
    conn.execute("DELETE FROM scheduling_runs")
    conn.execute("DELETE FROM ticket_history")
    conn.execute("DELETE FROM tickets")
    conn.execute("DELETE FROM users")
    conn.commit()
