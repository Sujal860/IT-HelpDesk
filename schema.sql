-- MySQL 8+ schema for the Phase 3 Multi-Organization IT Help Desk.
-- Existing Phase 2 installations are upgraded automatically by phase3_schema.py.
CREATE DATABASE IF NOT EXISTS helpdesk_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE helpdesk_db;

CREATE TABLE IF NOT EXISTS organizations (
  organization_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  organization_name VARCHAR(140) NOT NULL UNIQUE,
  contact_email VARCHAR(190) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
  user_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  role VARCHAR(20) NOT NULL DEFAULT 'USER',
  organization_id BIGINT NULL,
  created_at DATETIME NOT NULL,
  FOREIGN KEY (organization_id) REFERENCES organizations(organization_id),
  INDEX idx_users_organization (organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS organization_users (
  membership_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  organization_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  joined_at DATETIME NOT NULL,
  UNIQUE KEY uq_org_user (organization_id,user_id),
  FOREIGN KEY (organization_id) REFERENCES organizations(organization_id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS categories (
  category_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  category_name VARCHAR(80) NOT NULL UNIQUE,
  description VARCHAR(255) NOT NULL,
  default_priority INT NOT NULL DEFAULT 3,
  default_service_minutes INT NOT NULL DEFAULT 30
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  category_id BIGINT NOT NULL,
  organization_id BIGINT NULL,
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
  assignment_version INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_ticket_user FOREIGN KEY (user_id) REFERENCES users(user_id),
  CONSTRAINT fk_ticket_category FOREIGN KEY (category_id) REFERENCES categories(category_id),
  CONSTRAINT fk_ticket_organization FOREIGN KEY (organization_id) REFERENCES organizations(organization_id),
  INDEX idx_ticket_status_arrival (status, arrival_offset),
  INDEX idx_ticket_created (created_at),
  INDEX idx_tickets_organization (organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ticket_history (
  history_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ticket_id BIGINT NOT NULL,
  old_status VARCHAR(24) NULL,
  new_status VARCHAR(24) NOT NULL,
  changed_by VARCHAR(100) NOT NULL,
  changed_at DATETIME NOT NULL,
  note VARCHAR(1000) NULL,
  CONSTRAINT fk_history_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  INDEX idx_history_ticket_time (ticket_id, changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS scheduling_runs (
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
  notes VARCHAR(1000) NULL,
  context_switches INT NOT NULL DEFAULT 0,
  time_quantum INT NULL,
  context_switch_overhead INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS scheduling_results (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS scheduling_segments (
  segment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  result_id BIGINT NOT NULL,
  segment_number INT NOT NULL,
  start_time INT NOT NULL,
  end_time INT NOT NULL,
  UNIQUE KEY uq_result_segment (result_id,segment_number),
  FOREIGN KEY (result_id) REFERENCES scheduling_results(result_id) ON DELETE CASCADE,
  INDEX idx_segment_result (result_id,segment_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS technicians (
  technician_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  phone VARCHAR(30) NULL,
  password_hash VARCHAR(255) NULL,
  availability VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ticket_assignments (
  assignment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ticket_id BIGINT NOT NULL,
  technician_id BIGINT NOT NULL,
  assigned_by VARCHAR(100) NOT NULL,
  assigned_at DATETIME NOT NULL,
  released_at DATETIME NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  FOREIGN KEY (technician_id) REFERENCES technicians(technician_id),
  INDEX idx_assign_active (ticket_id,is_active),
  INDEX idx_assign_tech (technician_id,is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS technician_ratings (
  rating_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ticket_id BIGINT NOT NULL UNIQUE,
  technician_id BIGINT NOT NULL,
  requester_email VARCHAR(190) NOT NULL,
  rating TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  feedback VARCHAR(1000) NULL,
  created_at DATETIME NOT NULL,
  FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  FOREIGN KEY (technician_id) REFERENCES technicians(technician_id),
  INDEX idx_tech_rating (technician_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS service_ratings (
  rating_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ticket_id BIGINT NOT NULL UNIQUE,
  category_id BIGINT NOT NULL,
  requester_email VARCHAR(190) NOT NULL,
  rating TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  feedback VARCHAR(1000) NULL,
  created_at DATETIME NOT NULL,
  FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  FOREIGN KEY (category_id) REFERENCES categories(category_id),
  INDEX idx_service_rating_category (category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resources (
  resource_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  organization_id BIGINT NULL,
  resource_name VARCHAR(140) NOT NULL,
  description VARCHAR(500) NULL,
  total_quantity INT NOT NULL CHECK (total_quantity >= 0),
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  FOREIGN KEY (organization_id) REFERENCES organizations(organization_id),
  INDEX idx_resource_org (organization_id,is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resource_claims (
  claim_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  technician_id BIGINT NOT NULL,
  resource_id BIGINT NOT NULL,
  max_quantity INT NOT NULL CHECK (max_quantity >= 0),
  UNIQUE KEY uq_tech_resource_claim (technician_id,resource_id),
  FOREIGN KEY (technician_id) REFERENCES technicians(technician_id),
  FOREIGN KEY (resource_id) REFERENCES resources(resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resource_allocations (
  allocation_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ticket_id BIGINT NULL,
  technician_id BIGINT NOT NULL,
  resource_id BIGINT NOT NULL,
  quantity INT NOT NULL CHECK (quantity > 0),
  status VARCHAR(20) NOT NULL DEFAULT 'ALLOCATED',
  allocated_at DATETIME NOT NULL,
  released_at DATETIME NULL,
  FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE SET NULL,
  FOREIGN KEY (technician_id) REFERENCES technicians(technician_id),
  FOREIGN KEY (resource_id) REFERENCES resources(resource_id),
  INDEX idx_resource_active (resource_id,status),
  INDEX idx_allocation_tech (technician_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- Reporting views used by the admin workspace.
CREATE OR REPLACE VIEW v_technician_performance AS
SELECT te.technician_id, te.name, te.email, te.phone, te.availability, te.is_active,
       (SELECT COUNT(DISTINCT ta.ticket_id) FROM ticket_assignments ta WHERE ta.technician_id=te.technician_id) AS assigned_count,
       (SELECT AVG(tr.rating) FROM technician_ratings tr WHERE tr.technician_id=te.technician_id) AS avg_rating,
       (SELECT COUNT(*) FROM technician_ratings tr WHERE tr.technician_id=te.technician_id) AS rating_count
FROM technicians te;

CREATE OR REPLACE VIEW v_service_category_performance AS
SELECT c.category_id, c.category_name, AVG(sr.rating) AS avg_rating, COUNT(sr.rating_id) AS rating_count
FROM categories c LEFT JOIN service_ratings sr ON sr.category_id=c.category_id
GROUP BY c.category_id, c.category_name;
