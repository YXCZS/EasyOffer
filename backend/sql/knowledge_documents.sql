USE easyoffer;

CREATE TABLE IF NOT EXISTS knowledge_documents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  document_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  storage_path VARCHAR(500) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  mime_type VARCHAR(120) NOT NULL,
  file_size BIGINT UNSIGNED NOT NULL,
  status ENUM('processing','ready','failed') NOT NULL DEFAULT 'processing',
  error_message VARCHAR(500) NULL,
  chunk_count INT UNSIGNED NOT NULL DEFAULT 0,
  embedding_model VARCHAR(120) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_knowledge_document_id (document_id),
  UNIQUE KEY uq_knowledge_user_hash (user_id, content_hash),
  KEY idx_knowledge_user_status_updated (user_id, status, updated_at),
  CONSTRAINT fk_knowledge_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
