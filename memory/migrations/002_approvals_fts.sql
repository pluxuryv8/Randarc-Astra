-- Добавляем parent_run_id и purpose в runs
ALTER TABLE runs ADD COLUMN parent_run_id TEXT;
ALTER TABLE runs ADD COLUMN purpose TEXT;

-- Подтверждения для confirm gate
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  scope TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  proposed_actions TEXT NOT NULL,
  status TEXT NOT NULL,
  decided_at TEXT,
  decided_by TEXT
);
CREATE INDEX IF NOT EXISTS approvals_run_id_idx ON approvals(run_id);
CREATE INDEX IF NOT EXISTS approvals_task_id_idx ON approvals(task_id);

-- Хранилище хэша сессионного токена
CREATE TABLE IF NOT EXISTS session_tokens (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Индекс полнотекстового поиска (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  project_id,
  run_id,
  type,
  item_id,
  content,
  created_at,
  tags
);
