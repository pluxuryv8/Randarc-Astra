import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ArrowDown, Loader2 } from "lucide-react";
import ChatThread from "../widgets/ChatThread";
import TopBar from "../widgets/TopBar";
import NotificationCenter from "../widgets/NotificationCenter";
import ExportDialog from "../widgets/ExportDialog";
import Button from "../shared/ui/Button";
import Textarea from "../shared/ui/Textarea";
import Badge from "../shared/ui/Badge";
import Modal from "../shared/ui/Modal";
import { cn } from "../shared/utils/cn";
import { formatAuthDetail } from "../shared/utils/authDetail";
import { useAppStore } from "../shared/store/appStore";

const statusOptions = ["Думаю", "Формулирую", "Планирую", "Ищу информацию", "В работе", "Жду подтверждения", "Ошибка"];
const STORAGE_KEY = "preference_feedback";
const SCROLL_OFFSET = 80;

type FeedbackEntry = {
  id: string;
  chat_id: string;
  message_id: string;
  rating: "up" | "down";
  text?: string;
  ts: string;
};

function loadRatings(chatId: string | null): Record<string, "up" | "down"> {
  if (typeof window === "undefined" || !chatId) return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as FeedbackEntry[];
    return parsed
      .filter((entry) => entry.chat_id === chatId)
      .reduce<Record<string, "up" | "down">>((acc, entry) => {
        acc[entry.message_id] = entry.rating;
        return acc;
      }, {});
  } catch {
    return {};
  }
}

function saveFeedback(entry: FeedbackEntry) {
  if (typeof window === "undefined") return;
  const raw = localStorage.getItem(STORAGE_KEY);
  const existing = raw ? (JSON.parse(raw) as FeedbackEntry[]) : [];
  existing.push(entry);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(existing));
}

function deriveStatus({
  apiStatus,
  runStatus,
  activityPhase,
  mode,
  latestEventType
}: {
  apiStatus: string;
  runStatus?: string;
  activityPhase?: string;
  mode?: string;
  latestEventType?: string;
}) {
  if (apiStatus === "error") return "Ошибка";
  if (activityPhase === "waiting") return "Жду подтверждения";
  if (latestEventType === "llm_request_started" || latestEventType === "llm_route_decided") return "Думаю";
  if (latestEventType === "chat_response_generated" || latestEventType === "llm_request_succeeded") return "Формулирую";
  if (latestEventType === "source_found" || latestEventType === "source_fetched") return "Ищу информацию";
  if (latestEventType === "plan_created" || latestEventType === "step_planned" || latestEventType === "intent_decided")
    return "Планирую";
  if (runStatus === "planning") return "Планирую";
  if (runStatus === "running") return mode === "research" ? "Ищу информацию" : "В работе";
  if (runStatus === "paused") return "Думаю";
  if (runStatus === "failed" || runStatus === "canceled") return "Ошибка";
  return "Думаю";
}

function extractRunFailureReason(events: Array<{ type: string; message: string; payload?: Record<string, unknown>; run_id?: string }>, runId?: string) {
  const reversed = [...events].reverse();
  for (const event of reversed) {
    if (runId && event.run_id && event.run_id !== runId) continue;
    if (!["run_failed", "task_failed", "llm_request_failed", "local_llm_http_error"].includes(event.type)) continue;
    const payload = event.payload || {};
    const payloadError =
      typeof payload.error === "string"
        ? payload.error
        : typeof payload.error_type === "string"
          ? payload.error_type
          : typeof payload.detail === "string"
            ? payload.detail
            : null;
    const httpStatus = typeof payload.http_status_if_any === "number" ? payload.http_status_if_any : null;
    if (payloadError && httpStatus) {
      return `${payloadError} (HTTP ${httpStatus})`;
    }
    if (payloadError) {
      return payloadError;
    }
    if (event.message) {
      return event.message;
    }
  }
  return null;
}

function deriveConnectionBadge({
  authStatus,
  streamState,
  hint,
  lastStatus
}: {
  authStatus: string;
  streamState: string;
  hint?: string | null;
  lastStatus?: number | null;
}) {
  const text = (hint || "").toLowerCase();
  if (lastStatus === 401 || lastStatus === 403 || text.includes("401")) {
    return { tone: "danger" as const, label: "Подключение: 401 (токен)" };
  }
  if (text.includes("url/порт") || text.includes("порт")) {
    return { tone: "warn" as const, label: "Подключение: PORT MISMATCH" };
  }
  if (authStatus === "SERVER_UNREACHABLE" || streamState === "offline" || text.includes("api unreachable")) {
    return { tone: "danger" as const, label: "Подключение: REFUSED" };
  }
  if (streamState === "reconnecting") {
    return { tone: "warn" as const, label: "Подключение: reconnecting" };
  }
  if (authStatus === "CONNECTED" && streamState === "live") {
    return { tone: "success" as const, label: "Подключение: OK" };
  }
  return { tone: "muted" as const, label: "Подключение: проверка" };
}

function derivePendingAssistantText(deliveryState?: string, activeStatus?: string) {
  if (deliveryState === "queued") return "Astra приняла запрос и ждёт своей очереди…";
  if (activeStatus === "Ищу информацию") return "Astra ищет информацию…";
  if (activeStatus === "Планирую") return "Astra планирует ответ…";
  if (activeStatus === "Формулирую") return "Astra формулирует ответ…";
  return "Astra готовит ответ…";
}

export default function ChatPage() {
  const [composerValue, setComposerValue] = useState("");
  const [ratings, setRatings] = useState<Record<string, "up" | "down">>({});
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackError, setFeedbackError] = useState("");
  const [feedbackTarget, setFeedbackTarget] = useState<string | null>(null);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const conversationId = useAppStore((state) => state.lastSelectedChatId);
  const conversationMessages = useAppStore((state) => state.conversationMessages);
  const activity = useAppStore((state) => state.activity);
  const currentRun = useAppStore((state) => state.currentRun);
  const approvals = useAppStore((state) => state.approvals);
  const events = useAppStore((state) => state.events);
  const streamState = useAppStore((state) => state.streamState);
  const apiStatus = useAppStore((state) => state.apiStatus);
  const apiError = useAppStore((state) => state.apiError);
  const authStatus = useAppStore((state) => state.authStatus);
  const authError = useAppStore((state) => state.authError);
  const authDiagnostics = useAppStore((state) => state.authDiagnostics);
  const connectionHint = useAppStore((state) => state.connectionHint);
  const sendError = useAppStore((state) => state.sendError);
  const sending = useAppStore((state) => state.sending);
  const bootstrap = useAppStore((state) => state.bootstrap);
  const connectAuth = useAppStore((state) => state.connectAuth);
  const resetAuth = useAppStore((state) => state.resetAuth);
  const sendMessage = useAppStore((state) => state.sendMessage);
  const retrySend = useAppStore((state) => state.retrySend);
  const retryMessage = useAppStore((state) => state.retryMessage);
  const completeMessageTyping = useAppStore((state) => state.completeMessageTyping);
  const requestMore = useAppStore((state) => state.requestMore);
  const clearConversation = useAppStore((state) => state.clearConversation);
  const openRenameChat = useAppStore((state) => state.openRenameChat);
  const notifications = useAppStore((state) => state.notifications);
  const pauseActiveRun = useAppStore((state) => state.pauseActiveRun);
  const cancelActiveRun = useAppStore((state) => state.cancelActiveRun);

  const threadRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const lastSubmitAtRef = useRef(0);

  const messages = useMemo(() => {
    if (!conversationId) return [];
    return conversationMessages[conversationId] || [];
  }, [conversationId, conversationMessages]);

  const lastMessage = messages.length ? messages[messages.length - 1] : null;
  const hasAssistantTyping = messages.some((message) => message.role === "astra" && message.typing);

  const authDetail = formatAuthDetail(authDiagnostics.lastErrorDetail || authError);

  const activeStatus = useMemo(
    () =>
      deriveStatus({
        apiStatus,
        runStatus: currentRun?.status,
        activityPhase: activity?.phase,
        mode: currentRun?.mode,
        latestEventType: events[events.length - 1]?.type
      }),
    [activity?.phase, apiStatus, currentRun?.mode, currentRun?.status, events]
  );

  const runFailureReason = useMemo(
    () => extractRunFailureReason(events, currentRun?.id),
    [events, currentRun?.id]
  );

  const connectionBadge = useMemo(
    () =>
      deriveConnectionBadge({
        authStatus,
        streamState,
        hint: connectionHint,
        lastStatus: authDiagnostics.lastStatus
      }),
    [authDiagnostics.lastStatus, authStatus, connectionHint, streamState]
  );

  const hasApprovalPending = useMemo(
    () => approvals.some((item) => item.status === "pending") || activity?.phase === "waiting",
    [approvals, activity?.phase]
  );
  const canPause = currentRun?.status === "running";
  const canStop =
    currentRun?.status === "running" || currentRun?.status === "paused" || currentRun?.status === "planning";
  const showRunError =
    !sendError && (activity?.phase === "error" || currentRun?.status === "failed" || currentRun?.status === "canceled");
  const runErrorReason = runFailureReason || connectionHint || apiError || "Не удалось завершить выполнение.";
  const showPendingAssistant =
    Boolean(lastMessage) &&
    lastMessage?.role === "user" &&
    (lastMessage.delivery_state === "queued" || lastMessage.delivery_state === "sending") &&
    !hasAssistantTyping;
  const pendingAssistantText = derivePendingAssistantText(lastMessage?.delivery_state, activeStatus);

  useEffect(() => {
    setRatings(loadRatings(conversationId));
  }, [conversationId]);

  const handleScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distance < SCROLL_OFFSET;
    isAtBottomRef.current = atBottom;
    setShowScrollDown(!atBottom);
  };

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const el = threadRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  };

  useEffect(() => {
    if (isAtBottomRef.current) {
      requestAnimationFrame(() => scrollToBottom("auto"));
    }
  }, [messages]);

  useEffect(() => {
    requestAnimationFrame(() => scrollToBottom("auto"));
    isAtBottomRef.current = true;
    setShowScrollDown(false);
  }, [conversationId]);

  const handleRequestMore = async (messageId: string) => {
    await requestMore(messageId);
  };

  const handleThumbUp = (messageId: string) => {
    if (!conversationId) return;
    setRatings((prev) => ({ ...prev, [messageId]: "up" }));
    saveFeedback({
      id: `fb-${Date.now()}`,
      chat_id: conversationId,
      message_id: messageId,
      rating: "up",
      ts: new Date().toISOString()
    });
  };

  const handleThumbDown = (messageId: string) => {
    setFeedbackTarget(messageId);
    setFeedbackOpen(true);
    setFeedbackText("");
    setFeedbackError("");
  };

  const handleCopy = (messageId: string) => {
    const message = messages.find((item) => item.id === messageId);
    if (!message) return;
    navigator.clipboard?.writeText(message.text).catch(() => null);
  };

  const handleRetryMessage = async (messageId: string) => {
    await retryMessage(messageId);
  };

  const handleTypingDone = (messageId: string) => {
    if (!conversationId) return;
    completeMessageTyping(conversationId, messageId);
  };

  const submitFeedback = () => {
    if (!feedbackText.trim()) {
      setFeedbackError("Пожалуйста, уточните, что не так.");
      return;
    }
    if (!feedbackTarget || !conversationId) return;
    setRatings((prev) => ({ ...prev, [feedbackTarget]: "down" }));
    saveFeedback({
      id: `fb-${Date.now()}`,
      chat_id: conversationId,
      message_id: feedbackTarget,
      rating: "down",
      text: feedbackText.trim(),
      ts: new Date().toISOString()
    });
    setFeedbackOpen(false);
  };

  const canSend = authStatus === "CONNECTED";
  const canSubmit = canSend && Boolean(composerValue.trim());

  const handleSend = async () => {
    if (!canSubmit) return;
    const now = Date.now();
    if (now - lastSubmitAtRef.current < 250) return;
    lastSubmitAtRef.current = now;
    const payload = composerValue;
    setComposerValue("");
    const ok = await sendMessage(payload);
    if (!ok) {
      setComposerValue(payload);
    }
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    void handleSend();
  };

  const handleClearChat = () => {
    if (!conversationId) return;
    clearConversation(conversationId);
  };

  const handleExport = () => {
    setExportOpen(true);
  };

  return (
    <section className="chat-page">
      {authStatus === "SERVER_UNREACHABLE" ? (
        <div className="connection-banner">
          <div>
            <div className="connection-title">Сервер недоступен</div>
            <div className="connection-subtitle">{apiError || "Проверьте, что API запущен"}</div>
            <div className="connection-meta">API: {authDiagnostics.baseUrl}</div>
          </div>
          <Button type="button" variant="outline" onClick={() => void bootstrap()}>
            Повторить
          </Button>
        </div>
      ) : null}

      {connectionHint ? <div className="connection-hint">{connectionHint}</div> : null}
      {authStatus !== "SERVER_UNREACHABLE" && (authStatus === "NEED_CONNECT" || authStatus === "CONNECTING") ? (
        <div className="connection-banner">
          <div>
            <div className="connection-title">
              {authDiagnostics.tokenRequired ? "Нужен токен (strict)" : "Не удалось подключиться"}
            </div>
            <div className="connection-subtitle">
              {authDetail ||
                (authDiagnostics.tokenRequired
                  ? "Нажмите «Подключиться автоматически», чтобы создать токен."
                  : "Проверьте подключение и токен.")}
            </div>
            <div className="connection-meta">
              API: {authDiagnostics.baseUrl}
              {" · "}
              Запрос: {authDiagnostics.lastRequest || "—"}
              {" · "}
              Статус: {authDiagnostics.lastStatus ?? "—"}
              {" · "}
              Детали: {authDetail || "—"}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => void connectAuth("manual")}
            disabled={authStatus === "CONNECTING"}
          >
            {authStatus === "CONNECTING" ? (
              <>
                <Loader2 size={16} className="spin" />
                Переподключаюсь…
              </>
            ) : (
              authDiagnostics.tokenRequired
                ? "Подключиться автоматически"
                : "Переподключить"
            )}
          </Button>
          {authDiagnostics.tokenRequired === false ? null : (
            <Button type="button" variant="ghost" onClick={() => void resetAuth()}>
              Сбросить локальный токен
            </Button>
          )}
        </div>
      ) : null}
      {sendError ? (
        <div className="connection-banner">
          <div>
            <div className="connection-title">Не удалось отправить сообщение</div>
            <div className="connection-subtitle">{sendError}</div>
          </div>
          <Button type="button" variant="outline" onClick={() => void retrySend()}>
            Повторить
          </Button>
        </div>
      ) : null}
      {showRunError ? (
        <div className="connection-banner is-error">
          <div>
            <div className="connection-title">Возникла ошибка выполнения</div>
            <div className="connection-subtitle">{runErrorReason}</div>
          </div>
          <Button type="button" variant="outline" onClick={() => void retrySend()}>
            Повторить
          </Button>
        </div>
      ) : null}
      {hasApprovalPending ? (
        <div className="connection-banner is-warning">
          <div>
            <div className="connection-title">Нужно подтверждение</div>
            <div className="connection-subtitle">
              Astra остановилась перед потенциально опасным действием.
            </div>
          </div>
          <div className="connection-actions">
            <Button type="button" variant="ghost" onClick={() => void pauseActiveRun()} disabled={!canPause}>
              Пауза
            </Button>
            <Button type="button" variant="outline" onClick={() => void cancelActiveRun()} disabled={!canStop}>
              Остановить
            </Button>
          </div>
        </div>
      ) : null}

      <TopBar
        status={activeStatus}
        onClear={handleClearChat}
        onRename={() => {
          if (conversationId) openRenameChat(conversationId);
        }}
        onExport={handleExport}
        notificationsCount={notifications.length}
        onToggleNotifications={() => setNotificationsOpen((prev) => !prev)}
      />

      <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} />

      <div className="status-line">
        {statusOptions.map((status) => (
          <Badge
            key={status}
            tone={status === activeStatus ? "accent" : "muted"}
            size="sm"
            className={cn("status-chip", { "is-active": status === activeStatus })}
          >
            {status}
          </Badge>
        ))}
        <Badge tone={connectionBadge.tone} size="sm">
          {connectionBadge.label}
        </Badge>
        {streamState === "connecting" ? (
          <Badge tone="muted" size="sm">
            События: подключаюсь…
          </Badge>
        ) : null}
        {streamState === "live" ? (
          <Badge tone="success" size="sm">
            События: подключено
          </Badge>
        ) : null}
        {streamState === "reconnecting" ? (
          <Badge tone="warn" size="sm">
            События: переподключаюсь…
          </Badge>
        ) : null}
        {streamState === "offline" ? (
          <Badge tone="danger" size="sm">
            События: нет соединения
          </Badge>
        ) : null}
      </div>

      <div className="chat-thread-wrapper">
        {conversationId ? (
          messages.length ? (
            <ChatThread
              messages={messages}
              ratings={ratings}
              onRequestMore={handleRequestMore}
              onThumbUp={handleThumbUp}
              onThumbDown={handleThumbDown}
              onCopy={handleCopy}
              onRetryMessage={handleRetryMessage}
              onTypingDone={handleTypingDone}
              showPendingAssistant={showPendingAssistant}
              pendingAssistantText={pendingAssistantText}
              onScroll={handleScroll}
              scrollRef={threadRef}
            />
          ) : (
            <div className="empty-state chat-empty">Диалог создан. Напишите первое сообщение.</div>
          )
        ) : (
          <div className="empty-state chat-empty">Начните новый чат, чтобы продолжить.</div>
        )}
        {showScrollDown ? (
          <button type="button" className="chat-scroll-button" onClick={() => scrollToBottom("smooth")}>
            <ArrowDown size={16} />
            Вниз
          </button>
        ) : null}
      </div>

      {authStatus !== "CONNECTED" ? (
        <div className="composer-warning">Подключение неактивно. Переподключитесь, чтобы отправлять сообщения.</div>
      ) : null}
      {activity?.phase === "waiting" ? (
        <div className="composer-warning">Есть запрос на подтверждение. Можно продолжать диалог, но действия приостановлены.</div>
      ) : null}

      <div className="chat-composer">
        <Textarea
          value={composerValue}
          onChange={(event) => setComposerValue(event.target.value)}
          onKeyDown={handleComposerKeyDown}
          placeholder="Напишите сообщение…"
          disabled={!canSend}
        />
        <Button type="button" variant="primary" onClick={handleSend} disabled={!canSubmit}>
          {sending ? (
            <>
              <Loader2 size={16} className="spin" />
              Отправка…
            </>
          ) : (
            "Отправить"
          )}
        </Button>
      </div>

      <Modal open={feedbackOpen} title="Что не так?" onClose={() => setFeedbackOpen(false)}>
        <div className="feedback-form">
          <Textarea
            value={feedbackText}
            onChange={(event) => {
              setFeedbackText(event.target.value);
              if (feedbackError) setFeedbackError("");
            }}
            placeholder="Опишите проблему"
            required
          />
          {feedbackError ? <div className="ui-modal-error">{feedbackError}</div> : null}
          <div className="ui-modal-actions">
            <Button type="button" variant="ghost" onClick={() => setFeedbackOpen(false)}>
              Отмена
            </Button>
            <Button type="button" variant="primary" onClick={submitFeedback}>
              Отправить
            </Button>
          </div>
        </div>
      </Modal>

      <NotificationCenter open={notificationsOpen} onClose={() => setNotificationsOpen(false)} />
    </section>
  );
}
