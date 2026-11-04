-- SynapCart schema for Cloudflare D1 (SQLite).
-- Timestamps are ISO-8601 UTC strings ("2026-11-04T10:00:00.000Z").

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  hashed_password TEXT NOT NULL,
  full_name TEXT,
  language TEXT NOT NULL DEFAULT 'tr',
  currency TEXT NOT NULL DEFAULT 'TRY',
  -- Bumped on password change/reset to invalidate every issued JWT.
  token_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,

  -- Subscription. Premium only counts while plan_expires_at is in the future
  -- (NULL expiry = manual grant). plan_source: 'google' | 'apple' | NULL.
  plan TEXT NOT NULL DEFAULT 'free',
  plan_expires_at TEXT,
  plan_source TEXT,
  play_purchase_token TEXT UNIQUE,
  play_product_id TEXT,
  apple_original_transaction_id TEXT UNIQUE,
  apple_product_id TEXT,

  -- SHA-256 of single-use tokens (never the raw token).
  reset_token TEXT,
  reset_token_expires TEXT,
  delete_token TEXT,
  delete_token_expires TEXT
);
CREATE INDEX ix_users_reset_token ON users (reset_token);
CREATE INDEX ix_users_delete_token ON users (delete_token);

CREATE TABLE chat_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  title TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_chat_sessions_user_id ON chat_sessions (user_id);

CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  -- JSON-encoded list of products shown with an assistant answer.
  products TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_chat_messages_session_id ON chat_messages (session_id);

CREATE TABLE favorites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  price REAL,
  currency TEXT,
  source TEXT,
  link TEXT NOT NULL,
  thumbnail TEXT,
  created_at TEXT NOT NULL,
  -- Price alerts (premium).
  target_price REAL,
  last_checked_price REAL,
  last_checked_at TEXT,
  last_notified_price REAL,
  UNIQUE (user_id, link)
);
CREATE INDEX ix_favorites_target ON favorites (target_price) WHERE target_price IS NOT NULL;

-- Agent messages per user per UTC day (the daily quota).
CREATE TABLE usage_daily (
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  messages INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, date)
);

-- FCM registration tokens (Android and iOS) for price alerts.
CREATE TABLE device_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token TEXT NOT NULL UNIQUE,
  platform TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_device_tokens_user_id ON device_tokens (user_id);
