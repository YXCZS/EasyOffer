USE easyoffer;

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
