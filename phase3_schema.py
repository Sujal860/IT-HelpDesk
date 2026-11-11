"""Idempotent additive schema migration for Phase 3 features."""
from datetime import datetime


def init_phase3_schema(conn, db_mode: str):
    if db_mode == "mysql":
        statements = [
            """CREATE TABLE IF NOT EXISTS organizations (organization_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               organization_name VARCHAR(140) NOT NULL UNIQUE, contact_email VARCHAR(190) NULL,
               is_active TINYINT(1) NOT NULL DEFAULT 1, created_at DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS organization_users (membership_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               organization_id BIGINT NOT NULL, user_id BIGINT NOT NULL, joined_at DATETIME NOT NULL,
               UNIQUE KEY uq_org_user (organization_id,user_id),
               FOREIGN KEY (organization_id) REFERENCES organizations(organization_id) ON DELETE CASCADE,
               FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS technicians (technician_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               name VARCHAR(100) NOT NULL, email VARCHAR(190) NOT NULL UNIQUE, phone VARCHAR(30) NULL,
               password_hash VARCHAR(255) NULL, availability VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
               is_active TINYINT(1) NOT NULL DEFAULT 1, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS ticket_assignments (assignment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               ticket_id BIGINT NOT NULL, technician_id BIGINT NOT NULL, assigned_by VARCHAR(100) NOT NULL,
               assigned_at DATETIME NOT NULL, released_at DATETIME NULL, is_active TINYINT(1) NOT NULL DEFAULT 1,
               FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
               FOREIGN KEY (technician_id) REFERENCES technicians(technician_id), INDEX idx_assign_active (ticket_id,is_active),
               INDEX idx_assign_tech (technician_id,is_active)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS technician_ratings (rating_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               ticket_id BIGINT NOT NULL UNIQUE, technician_id BIGINT NOT NULL, requester_email VARCHAR(190) NOT NULL,
               rating TINYINT NOT NULL, feedback VARCHAR(1000) NULL, created_at DATETIME NOT NULL,
               FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
               FOREIGN KEY (technician_id) REFERENCES technicians(technician_id), CHECK (rating BETWEEN 1 AND 5),
               INDEX idx_tech_rating (technician_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS service_ratings (rating_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               ticket_id BIGINT NOT NULL UNIQUE, category_id BIGINT NOT NULL, requester_email VARCHAR(190) NOT NULL,
               rating TINYINT NOT NULL, feedback VARCHAR(1000) NULL, created_at DATETIME NOT NULL,
               FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
               FOREIGN KEY (category_id) REFERENCES categories(category_id), CHECK (rating BETWEEN 1 AND 5),
               INDEX idx_service_rating_category (category_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS scheduling_segments (segment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               result_id BIGINT NOT NULL, segment_number INT NOT NULL, start_time INT NOT NULL, end_time INT NOT NULL,
               FOREIGN KEY (result_id) REFERENCES scheduling_results(result_id) ON DELETE CASCADE,
               UNIQUE KEY uq_result_segment (result_id,segment_number), INDEX idx_segment_result (result_id,segment_number)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS resources (resource_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               organization_id BIGINT NULL, resource_name VARCHAR(140) NOT NULL, description VARCHAR(500) NULL,
               total_quantity INT NOT NULL, is_active TINYINT(1) NOT NULL DEFAULT 1, created_at DATETIME NOT NULL,
               FOREIGN KEY (organization_id) REFERENCES organizations(organization_id), CHECK (total_quantity >= 0),
               INDEX idx_resource_org (organization_id,is_active)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS resource_claims (claim_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               technician_id BIGINT NOT NULL, resource_id BIGINT NOT NULL, max_quantity INT NOT NULL,
               UNIQUE KEY uq_tech_resource_claim (technician_id,resource_id),
               FOREIGN KEY (technician_id) REFERENCES technicians(technician_id),
               FOREIGN KEY (resource_id) REFERENCES resources(resource_id), CHECK (max_quantity >= 0)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS resource_allocations (allocation_id BIGINT PRIMARY KEY AUTO_INCREMENT,
               ticket_id BIGINT NULL, technician_id BIGINT NOT NULL, resource_id BIGINT NOT NULL, quantity INT NOT NULL,
               status VARCHAR(20) NOT NULL DEFAULT 'ALLOCATED', allocated_at DATETIME NOT NULL, released_at DATETIME NULL,
               FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE SET NULL,
               FOREIGN KEY (technician_id) REFERENCES technicians(technician_id),
               FOREIGN KEY (resource_id) REFERENCES resources(resource_id), CHECK (quantity > 0),
               INDEX idx_resource_active (resource_id,status), INDEX idx_allocation_tech (technician_id,status)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        ]
        try:
            with conn.cursor() as cur:
                for statement in statements: cur.execute(statement)
                cur.execute("SHOW COLUMNS FROM users LIKE 'organization_id'")
                if not cur.fetchone(): cur.execute("ALTER TABLE users ADD COLUMN organization_id BIGINT NULL")
                cur.execute("SHOW COLUMNS FROM tickets LIKE 'organization_id'")
                if not cur.fetchone(): cur.execute("ALTER TABLE tickets ADD COLUMN organization_id BIGINT NULL")
                for table, column, ddl in [
                    ("scheduling_runs", "context_switches", "INT NOT NULL DEFAULT 0"),
                    ("scheduling_runs", "time_quantum", "INT NULL"),
                    ("scheduling_runs", "context_switch_overhead", "INT NOT NULL DEFAULT 0"),
                    ("tickets", "assignment_version", "INT NOT NULL DEFAULT 0"),
                ]:
                    cur.execute(f"SHOW COLUMNS FROM {table} LIKE '{column}'")
                    if not cur.fetchone(): cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                for table, index_name, columns in [
                    ("users", "idx_users_organization", "organization_id"),
                    ("tickets", "idx_tickets_organization", "organization_id"),
                ]:
                    cur.execute(f"SHOW INDEX FROM {table} WHERE Key_name='{index_name}'")
                    if not cur.fetchone(): cur.execute(f"CREATE INDEX {index_name} ON {table} ({columns})")
                for table, constraint, column in [
                    ("users", "fk_user_organization", "organization_id"),
                    ("tickets", "fk_ticket_organization", "organization_id"),
                ]:
                    cur.execute("SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", (table,constraint))
                    if not cur.fetchone(): cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} FOREIGN KEY ({column}) REFERENCES organizations(organization_id)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    else:
        statements = [
            "CREATE TABLE IF NOT EXISTS organizations (organization_id INTEGER PRIMARY KEY AUTOINCREMENT, organization_name TEXT NOT NULL UNIQUE, contact_email TEXT, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS organization_users (membership_id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, joined_at TEXT NOT NULL, UNIQUE(organization_id,user_id))",
            "CREATE TABLE IF NOT EXISTS technicians (technician_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, phone TEXT, password_hash TEXT, availability TEXT NOT NULL DEFAULT 'AVAILABLE', is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS ticket_assignments (assignment_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE, technician_id INTEGER NOT NULL REFERENCES technicians(technician_id), assigned_by TEXT NOT NULL, assigned_at TEXT NOT NULL, released_at TEXT, is_active INTEGER NOT NULL DEFAULT 1)",
            "CREATE TABLE IF NOT EXISTS technician_ratings (rating_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(ticket_id) ON DELETE CASCADE, technician_id INTEGER NOT NULL REFERENCES technicians(technician_id), requester_email TEXT NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), feedback TEXT, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS service_ratings (rating_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(ticket_id) ON DELETE CASCADE, category_id INTEGER NOT NULL REFERENCES categories(category_id), requester_email TEXT NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), feedback TEXT, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS scheduling_segments (segment_id INTEGER PRIMARY KEY AUTOINCREMENT, result_id INTEGER NOT NULL REFERENCES scheduling_results(result_id) ON DELETE CASCADE, segment_number INTEGER NOT NULL, start_time INTEGER NOT NULL, end_time INTEGER NOT NULL, UNIQUE(result_id,segment_number))",
            "CREATE TABLE IF NOT EXISTS resources (resource_id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER REFERENCES organizations(organization_id), resource_name TEXT NOT NULL, description TEXT, total_quantity INTEGER NOT NULL CHECK(total_quantity >= 0), is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS resource_claims (claim_id INTEGER PRIMARY KEY AUTOINCREMENT, technician_id INTEGER NOT NULL REFERENCES technicians(technician_id), resource_id INTEGER NOT NULL REFERENCES resources(resource_id), max_quantity INTEGER NOT NULL CHECK(max_quantity >= 0), UNIQUE(technician_id,resource_id))",
            "CREATE TABLE IF NOT EXISTS resource_allocations (allocation_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER REFERENCES tickets(ticket_id) ON DELETE SET NULL, technician_id INTEGER NOT NULL REFERENCES technicians(technician_id), resource_id INTEGER NOT NULL REFERENCES resources(resource_id), quantity INTEGER NOT NULL CHECK(quantity > 0), status TEXT NOT NULL DEFAULT 'ALLOCATED', allocated_at TEXT NOT NULL, released_at TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_assign_active ON ticket_assignments(ticket_id,is_active)",
            "CREATE INDEX IF NOT EXISTS idx_assign_tech ON ticket_assignments(technician_id,is_active)",
            "CREATE INDEX IF NOT EXISTS idx_tech_rating ON technician_ratings(technician_id)",
            "CREATE INDEX IF NOT EXISTS idx_service_rating_category ON service_ratings(category_id)",
            "CREATE INDEX IF NOT EXISTS idx_segment_result ON scheduling_segments(result_id,segment_number)",
            "CREATE INDEX IF NOT EXISTS idx_resource_org ON resources(organization_id,is_active)",
            "CREATE INDEX IF NOT EXISTS idx_resource_active ON resource_allocations(resource_id,status)",
            "CREATE INDEX IF NOT EXISTS idx_allocation_tech ON resource_allocations(technician_id,status)",
        ]
        for statement in statements:
            conn.execute(statement)
        user_columns = {row['name'] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if 'organization_id' not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN organization_id INTEGER")
        ticket_columns = {row['name'] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()}
        if 'organization_id' not in ticket_columns:
            conn.execute("ALTER TABLE tickets ADD COLUMN organization_id INTEGER")
        if 'assignment_version' not in ticket_columns:
            conn.execute("ALTER TABLE tickets ADD COLUMN assignment_version INTEGER NOT NULL DEFAULT 0")
        # Organization columns must exist before indexes and triggers reference them.
        for statement in [
            "CREATE INDEX IF NOT EXISTS idx_users_organization ON users(organization_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_organization ON tickets(organization_id)",
            "CREATE TRIGGER IF NOT EXISTS trg_ticket_org_insert BEFORE INSERT ON tickets WHEN NEW.organization_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id) BEGIN SELECT RAISE(ABORT,'Invalid ticket organization'); END",
            "CREATE TRIGGER IF NOT EXISTS trg_ticket_org_update BEFORE UPDATE OF organization_id ON tickets WHEN NEW.organization_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id) BEGIN SELECT RAISE(ABORT,'Invalid ticket organization'); END",
            "CREATE TRIGGER IF NOT EXISTS trg_user_org_insert BEFORE INSERT ON users WHEN NEW.organization_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id) BEGIN SELECT RAISE(ABORT,'Invalid user organization'); END",
            "CREATE TRIGGER IF NOT EXISTS trg_user_org_update BEFORE UPDATE OF organization_id ON users WHEN NEW.organization_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id) BEGIN SELECT RAISE(ABORT,'Invalid user organization'); END",
        ]:
            conn.execute(statement)
        run_columns = {row['name'] for row in conn.execute("PRAGMA table_info(scheduling_runs)").fetchall()}
        if 'context_switches' not in run_columns: conn.execute("ALTER TABLE scheduling_runs ADD COLUMN context_switches INTEGER NOT NULL DEFAULT 0")
        if 'time_quantum' not in run_columns: conn.execute("ALTER TABLE scheduling_runs ADD COLUMN time_quantum INTEGER")
        if 'context_switch_overhead' not in run_columns: conn.execute("ALTER TABLE scheduling_runs ADD COLUMN context_switch_overhead INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    # Recreate compact reporting views on every migration so they stay aligned with the schema.
    view_statements = [
        "DROP VIEW IF EXISTS v_technician_performance",
        "CREATE VIEW v_technician_performance AS SELECT te.technician_id, te.name, te.email, te.phone, te.availability, te.is_active, (SELECT COUNT(DISTINCT ta.ticket_id) FROM ticket_assignments ta WHERE ta.technician_id=te.technician_id) AS assigned_count, (SELECT AVG(tr.rating) FROM technician_ratings tr WHERE tr.technician_id=te.technician_id) AS avg_rating, (SELECT COUNT(*) FROM technician_ratings tr WHERE tr.technician_id=te.technician_id) AS rating_count FROM technicians te",
        "DROP VIEW IF EXISTS v_service_category_performance",
        "CREATE VIEW v_service_category_performance AS SELECT c.category_id, c.category_name, AVG(sr.rating) AS avg_rating, COUNT(sr.rating_id) AS rating_count FROM categories c LEFT JOIN service_ratings sr ON sr.category_id=c.category_id GROUP BY c.category_id,c.category_name",
    ]
    for statement in view_statements:
        conn.execute(statement)
    conn.commit()
    stamp = datetime.now().isoformat(timespec='seconds')
    from database import fetch_one
    org = fetch_one("SELECT organization_id FROM organizations ORDER BY organization_id LIMIT 1")
    if not org:
        conn.execute("INSERT INTO organizations (organization_name, contact_email, created_at) VALUES (?, ?, ?)",
                     ("Campus Demo", "support@example.edu", stamp))
        conn.commit()
        org = fetch_one("SELECT organization_id FROM organizations ORDER BY organization_id LIMIT 1")
    org_id = int(org['organization_id'])
    conn.execute("UPDATE users SET organization_id=? WHERE organization_id IS NULL", (org_id,))
    conn.execute("UPDATE tickets SET organization_id=? WHERE organization_id IS NULL", (org_id,))
    if db_mode == "mysql":
        conn.execute("INSERT IGNORE INTO organization_users (organization_id,user_id,joined_at) SELECT organization_id,user_id,created_at FROM users WHERE organization_id IS NOT NULL")
    else:
        conn.execute("INSERT OR IGNORE INTO organization_users (organization_id,user_id,joined_at) SELECT organization_id,user_id,created_at FROM users WHERE organization_id IS NOT NULL")
    conn.commit()
