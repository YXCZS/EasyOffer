-- EasyOffer user system schema for MySQL 8.x.
-- This script is idempotent and can be applied to a fresh or existing database.

CREATE DATABASE IF NOT EXISTS easyoffer
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE easyoffer;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  openid VARCHAR(64) NOT NULL,
  nickname VARCHAR(100) NOT NULL DEFAULT '学习者',
  avatar_url VARCHAR(500) NOT NULL DEFAULT '',
  total_xp INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_openid (openid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_sessions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  quiz_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(255) NOT NULL,
  summary TEXT NOT NULL,
  user_input TEXT NOT NULL,
  questions_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_quiz_sessions_quiz_id (quiz_id),
  KEY idx_quiz_sessions_user_created (user_id, created_at),
  CONSTRAINT fk_quiz_sessions_user
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS answer_records (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  quiz_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  records_json JSON NOT NULL,
  total_questions INT UNSIGNED NOT NULL,
  correct_count INT UNSIGNED NOT NULL,
  accuracy DECIMAL(5,2) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_answer_records_quiz_id (quiz_id),
  KEY idx_answer_records_user_created (user_id, created_at),
  CONSTRAINT fk_answer_records_user
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_answer_records_quiz
    FOREIGN KEY (quiz_id) REFERENCES quiz_sessions (quiz_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  quiz_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  report_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_reports_quiz_id (quiz_id),
  KEY idx_reports_user_created (user_id, created_at),
  CONSTRAINT fk_reports_user
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_reports_quiz
    FOREIGN KEY (quiz_id) REFERENCES quiz_sessions (quiz_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_progress (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  quiz_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  role VARCHAR(32) NOT NULL DEFAULT 'general',
  difficulty VARCHAR(16) NOT NULL DEFAULT 'medium',
  status VARCHAR(32) NOT NULL DEFAULT 'in_progress',
  current_index INT UNSIGNED NOT NULL DEFAULT 0,
  answer_records_json JSON NOT NULL,
  answered_count INT UNSIGNED NOT NULL DEFAULT 0,
  total_questions INT UNSIGNED NOT NULL,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  last_error VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  completed_at DATETIME NULL,
  abandoned_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_quiz_progress_quiz_id (quiz_id),
  KEY idx_quiz_progress_user_status_updated (user_id, status, updated_at),
  CONSTRAINT fk_quiz_progress_quiz
    FOREIGN KEY (quiz_id) REFERENCES quiz_sessions (quiz_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_quiz_progress_user
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_generation_tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  request_json JSON NOT NULL,
  status ENUM('queued','generating','completed','failed','expired') NOT NULL DEFAULT 'queued',
  generated_count INT UNSIGNED NOT NULL DEFAULT 0,
  total_count INT UNSIGNED NOT NULL DEFAULT 6,
  questions_json JSON NOT NULL,
  answer_records_json JSON NOT NULL,
  current_index INT UNSIGNED NOT NULL DEFAULT 0,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  progress_version INT UNSIGNED NOT NULL DEFAULT 1,
  title VARCHAR(255) NOT NULL DEFAULT '',
  summary TEXT NOT NULL,
  quiz_id VARCHAR(80) NULL,
  quiz_json JSON NULL,
  error_message VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_quiz_generation_task_id (task_id),
  UNIQUE KEY uq_quiz_generation_quiz_id (quiz_id),
  KEY idx_quiz_generation_user_status (user_id, status, updated_at),
  KEY idx_quiz_generation_expiry (status, expires_at),
  CONSTRAINT fk_quiz_generation_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
