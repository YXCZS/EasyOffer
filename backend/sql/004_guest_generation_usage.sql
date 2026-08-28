USE easyoffer;

CREATE TABLE IF NOT EXISTS guest_generation_usage (
  guest_token_hash CHAR(64) NOT NULL,
  usage_date DATE NOT NULL,
  total_count INT UNSIGNED NOT NULL DEFAULT 0,
  active_count INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (guest_token_hash, usage_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
