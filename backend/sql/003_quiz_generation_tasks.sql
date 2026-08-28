USE easyoffer;

CREATE TABLE IF NOT EXISTS quiz_generation_tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  guest_token_hash CHAR(64) NULL,
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
  KEY idx_quiz_generation_guest_status (guest_token_hash, status, updated_at),
  KEY idx_quiz_generation_expiry (status, expires_at),
  CONSTRAINT fk_quiz_generation_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
