CREATE TABLE IF NOT EXISTS quiz_visual_assets (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  asset_id VARCHAR(80) NOT NULL,
  dedupe_key VARCHAR(180) NOT NULL,
  task_id VARCHAR(80) NULL,
  quiz_id VARCHAR(80) NULL,
  question_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  guest_token_hash CHAR(64) NULL,
  mode ENUM('image') NOT NULL DEFAULT 'image',
  visualization_type VARCHAR(30) NOT NULL DEFAULT 'conceptual',
  provider VARCHAR(50) NOT NULL DEFAULT 'dashscope',
  model_name VARCHAR(100) NOT NULL DEFAULT 'z-image-turbo',
  status ENUM('pending','generating','uploading','ready','failed') NOT NULL DEFAULT 'pending',
  prompt_hash CHAR(64) NOT NULL,
  image_prompt VARCHAR(1200) NOT NULL,
  alt_text VARCHAR(200) NOT NULL DEFAULT '',
  cos_key VARCHAR(500) NULL,
  image_url VARCHAR(2000) NULL,
  mime_type VARCHAR(100) NULL,
  width INT NULL,
  height INT NULL,
  error_message VARCHAR(500) NULL,
  retry_count INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_visual_asset_id (asset_id),
  UNIQUE KEY uq_visual_asset_dedupe (dedupe_key),
  KEY idx_visual_asset_task (task_id, status),
  KEY idx_visual_asset_quiz (quiz_id, question_id),
  CONSTRAINT fk_visual_asset_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Existing installations should run the following once if the table predates
-- visualization_type. The application startup migration performs the same
-- idempotent upgrade and ignores duplicate-column errors.
-- ALTER TABLE quiz_visual_assets
--   ADD COLUMN visualization_type VARCHAR(30) NOT NULL DEFAULT 'conceptual' AFTER mode;
