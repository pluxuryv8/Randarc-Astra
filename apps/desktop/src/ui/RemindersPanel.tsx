import type { Reminder } from "../types";

type RemindersPanelProps = {
  items: Reminder[];
  loading: boolean;
  error?: string | null;
  onRefresh: () => void;
  onCancel: (id: string) => void;
  onClose: () => void;
};

function formatDue(dueAt: string) {
  const ts = Date.parse(dueAt);
  if (Number.isNaN(ts)) return dueAt;
  const dt = new Date(ts);
  return dt.toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" });
}

export default function RemindersPanel({ items, loading, error, onRefresh, onCancel, onClose }: RemindersPanelProps) {
  const pending = items.filter((item) => item.status === "pending" || item.status === "sending");
  const done = items.filter((item) => item.status !== "pending" && item.status !== "sending");

  return (
    <div className="panel reminders-panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">Reminders</div>
          <div className="panel-subtitle">Локальные напоминания</div>
        </div>
        <button className="btn ghost small" onClick={onClose} title="Закрыть">
          ✕
        </button>
      </div>

      {error ? <div className="banner error">{error}</div> : null}

      <div className="panel-section">
        <div className="section-title">Pending</div>
        <button className="btn ghost small" onClick={onRefresh} disabled={loading}>
          {loading ? "..." : "Обновить"}
        </button>
        {pending.length === 0 && !loading ? <div className="empty">Нет активных напоминаний</div> : null}
        <div className="reminder-list">
          {pending.map((item) => (
            <div key={item.id} className="reminder-card">
              <div className="reminder-head">
                <div className="reminder-title">{item.text}</div>
                <div className="reminder-meta">{formatDue(item.due_at)}</div>
              </div>
              <div className="reminder-actions">
                <span className="tag">{item.delivery}</span>
                <button className="btn ghost small" onClick={() => onCancel(item.id)}>
                  Cancel
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel-section">
        <div className="section-title">Done</div>
        {done.length === 0 && !loading ? <div className="empty">Нет завершённых</div> : null}
        <div className="reminder-list">
          {done.map((item) => (
            <div key={item.id} className={`reminder-card ${item.status}`}>
              <div className="reminder-head">
                <div className="reminder-title">{item.text}</div>
                <div className="reminder-meta">{formatDue(item.due_at)}</div>
              </div>
              <div className="reminder-actions">
                <span className={`pill ${item.status === "sent" ? "ok" : item.status === "failed" ? "error" : "muted"}`}>
                  {item.status}
                </span>
                {item.last_error ? <span className="muted">{item.last_error}</span> : null}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
