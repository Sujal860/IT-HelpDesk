-- MySQL 8+ schema for the 40% phase prototype.
-- app.py can initialise these tables automatically when DB_MODE=mysql.
CREATE DATABASE IF NOT EXISTS helpdesk_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE helpdesk_db;

CREATE TABLE IF NOT EXISTS users (
  user_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  role VARCHAR(20) NOT NULL DEFAULT 'USER',
  created_at DATETIME NOT NULL
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
  notes VARCHAR(1000) NULL
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
