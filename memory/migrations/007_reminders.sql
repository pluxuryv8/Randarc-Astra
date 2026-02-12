CREATE TABLE IF NOT EXISTS reminders (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  due_at TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL,
  delivery TEXT NOT NULL,
  last_error TEXT,
  run_id TEXT,
  source TEXT,
  sent_at TEXT,
  updated_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at);
