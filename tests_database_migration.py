"""SQLite migration checks proving Phase 3 upgrades preserve Phase 2 data."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import database
from phase3_schema import init_phase3_schema


class FakeFlaskG(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        self.pop(name, None)


class Phase3MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.path = Path(self.temp_file.name)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_phase2_schema_with_data()
        self.original_g = database.g
        database.g = FakeFlaskG(helpdesk_db_conn=self.conn)

    def tearDown(self):
        self.conn.close()
        database.g = self.original_g
        self.path.unlink(missing_ok=True)

    def _create_phase2_schema_with_data(self):
        self.conn.executescript("""
        CREATE TABLE users(
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'USER', created_at TEXT NOT NULL
        );
        CREATE TABLE categories(
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT NOT NULL UNIQUE, description TEXT NOT NULL,
            default_priority INTEGER NOT NULL DEFAULT 3,
            default_service_minutes INTEGER NOT NULL DEFAULT 30
        );
        CREATE TABLE tickets(
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            category_id INTEGER NOT NULL REFERENCES categories(category_id),
            title TEXT NOT NULL, description TEXT NOT NULL, location_or_asset TEXT,
            priority INTEGER NOT NULL DEFAULT 3, status TEXT NOT NULL DEFAULT 'READY',
            estimated_service_minutes INTEGER NOT NULL DEFAULT 30,
            arrival_offset INTEGER NOT NULL DEFAULT 0, estimated_wait_minutes INTEGER,
            estimated_completion_at TEXT, confirmed_target_at TEXT, actual_started_at TEXT,
            resolved_at TEXT, resolution_notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE scheduling_runs(
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, algorithm TEXT NOT NULL,
            engine_used TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
            simulation_anchor_at TEXT NOT NULL, ticket_count INTEGER NOT NULL,
            avg_waiting_time REAL NOT NULL, avg_response_time REAL NOT NULL,
            avg_turnaround_time REAL NOT NULL, throughput REAL NOT NULL,
            utilization_percent REAL NOT NULL, notes TEXT
        );
        CREATE TABLE scheduling_results(
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES scheduling_runs(run_id),
            ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id),
            queue_order INTEGER NOT NULL, arrival_time INTEGER NOT NULL,
            service_time INTEGER NOT NULL, start_time INTEGER NOT NULL,
            completion_time INTEGER NOT NULL, waiting_time INTEGER NOT NULL,
            turnaround_time INTEGER NOT NULL, response_time INTEGER NOT NULL
        );
        INSERT INTO users(name,email,role,created_at)
        VALUES('Legacy Requester','legacy@example.com','USER','2025-01-01T09:00:00');
        INSERT INTO categories(category_name,description)
        VALUES('Network','Legacy category');
        INSERT INTO tickets(user_id,category_id,title,description,created_at,updated_at)
        VALUES(1,1,'Legacy ticket','Keep this row','2025-01-02T09:00:00','2025-01-02T09:00:00');
        """)
        self.conn.commit()

    def test_existing_phase2_data_is_preserved_and_attached_to_default_org(self):
        init_phase3_schema(self.conn, "sqlite")
        ticket = self.conn.execute(
            "SELECT title,organization_id FROM tickets WHERE ticket_id=1"
        ).fetchone()
        user = self.conn.execute(
            "SELECT email,organization_id FROM users WHERE user_id=1"
        ).fetchone()
        self.assertEqual(ticket["title"], "Legacy ticket")
        self.assertEqual(ticket["organization_id"], 1)
        self.assertEqual(user["email"], "legacy@example.com")
        self.assertEqual(user["organization_id"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM organization_users").fetchone()[0], 1)

    def test_migration_is_idempotent_and_creates_reporting_views(self):
        init_phase3_schema(self.conn, "sqlite")
        init_phase3_schema(self.conn, "sqlite")
        view_names = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()
        }
        self.assertEqual(view_names, {
            "v_technician_performance", "v_service_category_performance"
        })
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
