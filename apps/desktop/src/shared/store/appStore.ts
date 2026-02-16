import { create } from "zustand";
import type {
  Activity,
  ActivityStep,
  ActivityStepStatus,
  AppPage,
  ConversationSummary,
  Message,
  NotificationItem,
  OverlayBehavior,
  OverlayCorner
} from "../types/ui";
import type { Approval, EventItem, PlanStep, Project, Reminder, Run, RunIntentResponse, Snapshot, UserMemory } from "../types/api";
import {
  cancelRun,
  cancelReminder,
  createProject,
  createReminder,
  deleteUserMemory,
  listProjects,
  listReminders,
  listRuns,
  listUserMemory,
  pauseRun
} from "../api/client";
import { mergeEvents } from "../utils/events";
import { createRunService } from "../api/runService";
import type { StreamState as RawStreamState } from "../api/eventStream";
import { ApiError, isAuthError, isNetworkError } from "../api/errors";
import {
  checkStatus,
  clearToken,
  connect as connectController,
  getDiagnostics,
  getToken,
  regenerateToken,
  setLastError
} from "../api/authController";
import { PHRASES, nameFromMeta, withName } from "../assistantPhrases";

const runService = createRunService();

const STORAGE_KEYS = {
  sidebarWidth: "astra.ui.sidebarWidth",
  activityWidth: "astra.ui.activityWidth",
  activityOpen: "astra.ui.activityOpen",
  lastSelectedPage: "astra.ui.lastSelectedPage",
  lastSelectedChatId: "astra.ui.lastSelectedChatId",
  density: "astra.ui.density",
  grain: "astra.ui.grain",
  activityDetailed: "astra.ui.activityDetailed",
  defaultActivityOpen: "astra.ui.defaultActivityOpen",
  overlayOpen: "astra.ui.overlayOpen",
  overlayBehavior: "astra.ui.overlay.behavior",
  overlayCorner: "astra.ui.overlay.cornerPreference",
  overlayBounds: "astra.ui.overlayBounds",
  notifications: "astra.ui.notifications",
  conversations: "astra.ui.conversations",
  conversationMessages: "astra.ui.conversationMessages",
  legacyTitleOverrides: "astra.ui.runTitleOverrides",
  legacyHiddenRuns: "astra.ui.hiddenRuns"
} as const;

export const DEFAULT_SIDEBAR_WIDTH = 300;
export const DEFAULT_ACTIVITY_WIDTH = 340;

const EVENT_BUFFER_LIMIT = 2000;
const RUNS_LIMIT = 80;
const POLL_INTERVAL_MS = 5000;
const MESSAGE_LIMIT = 240;
const CONVERSATION_LIMIT = 200;
const NOTIFICATION_TTL_MS = 6000;
const NOTIFICATION_TTL_WARNING_MS = 10000;
const NOTIFICATION_TTL_ERROR_MS = 18000;

type PendingSendJob = {
  messageId: string;
  conversationId: string;
  queryText: string;
  titleSeed: string;
  parentRunId: string | null;
  createdAt: string;
};

const EVENT_TYPES = [
  "approval_approved",
  "approval_rejected",
  "approval_resolved",
  "approval_requested",
  "artifact_created",
  "autopilot_action",
  "autopilot_state",
  "chat_response_generated",
  "clarify_requested",
  "conflict_detected",
  "fact_extracted",
  "intent_decided",
  "llm_provider_used",
  "llm_budget_exceeded",
  "llm_request_failed",
  "llm_request_started",
  "llm_request_succeeded",
  "llm_request_sanitized",
  "llm_route_decided",
  "local_llm_http_error",
  "memory_deleted",
  "memory_list_viewed",
  "memory_save_requested",
  "memory_saved",
  "micro_action_executed",
  "micro_action_proposed",
  "observation_captured",
  "ocr_cached_hit",
  "ocr_performed",
  "plan_created",
  "run_canceled",
  "run_created",
  "run_done",
  "run_failed",
  "run_paused",
  "run_resumed",
  "run_started",
  "reminder_cancelled",
  "reminder_created",
  "reminder_due",
  "reminder_failed",
  "reminder_sent",
  "source_fetched",
  "source_found",
  "step_cancelled_by_user",
  "step_execution_finished",
  "step_execution_started",
  "step_paused_for_approval",
  "step_planned",
  "step_retrying",
  "step_waiting",
  "task_done",
  "task_failed",
  "task_progress",
  "task_queued",
  "task_retried",
  "task_started",
  "user_action_required",
  "verification_done",
  "verification_result"
];

const hasWindow = typeof window !== "undefined";

function getStorageValue(key: string) {
  if (!hasWindow) return null;
  return window.localStorage.getItem(key);
}

function setStorageValue(key: string, value: string) {
  if (!hasWindow) return;
  window.localStorage.setItem(key, value);
}

function loadNumber(key: string, fallback: number) {
  const raw = getStorageValue(key);
  if (!raw) return fallback;
  const num = Number(raw);
  return Number.isFinite(num) ? num : fallback;
}

function loadBoolean(key: string, fallback: boolean) {
  const raw = getStorageValue(key);
  if (!raw) return fallback;
  return raw === "true";
}

function loadString(key: string, fallback: string) {
  const raw = getStorageValue(key);
  return raw ?? fallback;
}

function loadJSON<T>(key: string, fallback: T) {
  const raw = getStorageValue(key);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function createId(prefix: string) {
  if (hasWindow && "crypto" in window && typeof window.crypto.randomUUID === "function") {
    return `${prefix}-${window.crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function truncate(text: string, max = 48) {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function mapRunIcons(run?: Run | null) {
  if (!run) return ["blue", "teal"];
  return run.mode === "research" ? ["blue", "teal"] : ["teal", "amber"];
}

function buildConversationTitle(text: string) {
  return truncate(text.trim() || "Новый чат", 56);
}

function mapStepStatus(status?: string): ActivityStepStatus {
  if (status === "done") return "done";
  if (status === "running") return "active";
  if (status === "failed" || status === "canceled") return "error";
  return "pending";
}

export function phaseLabel(phase: Activity["phase"]) {
  switch (phase) {
    case "planning":
      return "Планирую";
    case "executing":
      return "Выполняю";
    case "review":
      return "Проверяю";
    case "waiting":
      return "Жду подтверждения";
    case "error":
      return "Ошибка";
    default:
      return "Планирую";
  }
}

export function stepLabel(status: ActivityStepStatus) {
  switch (status) {
    case "done":
      return "Готово";
    case "active":
      return "В работе";
    case "error":
      return "Ошибка";
    default:
      return "Ожидание";
  }
}

function derivePhase(run?: Run | null, approvals?: Approval[]) {
  if (!run) return "planning" as const;
  const pending = approvals?.some((approval) => approval.status === "pending");
  if (pending) return "waiting" as const;
  if (run.status === "planning") return "planning" as const;
  if (run.status === "running") return "executing" as const;
  if (run.status === "paused") return "waiting" as const;
  if (run.status === "done") return "review" as const;
  if (run.status === "failed" || run.status === "canceled") return "error" as const;
  return "planning" as const;
}

function detailsFromEvents(events: EventItem[]): string[] {
  const lines: string[] = [];
  const recent = [...events].slice(-8).reverse();
  for (const event of recent) {
    if (lines.length >= 3) break;
    switch (event.type) {
      case "plan_created":
        lines.push("Планирую.");
        break;
      case "step_execution_started":
      case "task_started":
        lines.push("Выполняю.");
        break;
      case "step_execution_finished":
      case "task_done":
        lines.push("Шаг завершён.");
        break;
      case "approval_requested":
      case "step_paused_for_approval":
        lines.push(PHRASES.confirmDanger);
        break;
      case "run_failed":
      case "task_failed":
      case "llm_request_failed":
        lines.push(PHRASES.error);
        break;
      case "run_done":
        lines.push(PHRASES.done);
        break;
      case "local_llm_http_error":
        lines.push("Ошибка локальной модели. Проверьте настройки.");
        break;
      default:
        break;
    }
  }
  return lines;
}

function notificationFromReminderEvent(event: EventItem): NotificationItem | null {
  if (!event.type.startsWith("reminder_")) return null;
  if (!["reminder_sent", "reminder_failed", "reminder_due"].includes(event.type)) return null;
  const payload = event.payload || {};
  const text =
    typeof payload.text === "string"
      ? payload.text
      : typeof payload.message === "string"
        ? payload.message
        : event.message;
  const title =
    event.type === "reminder_sent"
      ? "Напоминание отправлено"
      : event.type === "reminder_failed"
        ? "Ошибка напоминания"
        : "Напоминание сработало";
  const severity = event.type === "reminder_failed" ? "error" : "success";
  return {
    id: `reminder-event-${event.id}`,
    ts: new Date((event.ts || Date.now()) * (event.ts && event.ts < 1e12 ? 1000 : 1)).toISOString(),
    title,
    body: text || "—",
    severity
  };
}

function activityFromSnapshot(snapshot: Snapshot, events: EventItem[]): Activity {
  const steps: ActivityStep[] = (snapshot.plan || []).map((step) => ({
    id: step.id,
    title: step.title,
    status: mapStepStatus(step.status)
  }));

  return {
    run_id: snapshot.run.id,
    phase: derivePhase(snapshot.run, snapshot.approvals),
    steps,
    details: detailsFromEvents(events)
  };
}

function buildPlanMessage(plan: PlanStep[]): string | null {
  if (!plan.length) return null;
  const lines = plan
    .slice(0, 6)
    .map((step, index) => `${index + 1}. ${step.title}`)
    .join("\n");
  return `План:\n${lines}`;
}

function loadConversations(): ConversationSummary[] {
  return loadJSON<ConversationSummary[]>(STORAGE_KEYS.conversations, []);
}

function saveConversations(conversations: ConversationSummary[]) {
  setStorageValue(STORAGE_KEYS.conversations, JSON.stringify(conversations.slice(0, CONVERSATION_LIMIT)));
}

function loadConversationMessages(): Record<string, Message[]> {
  const raw = loadJSON<Record<string, Message[]>>(STORAGE_KEYS.conversationMessages, {});
  const normalized: Record<string, Message[]> = {};
  for (const [conversationId, messages] of Object.entries(raw)) {
    normalized[conversationId] = (messages || []).map((message) => ({
      ...message,
      typing: false
    }));
  }
  return normalized;
}

function loadNotifications(): NotificationItem[] {
  return loadJSON<NotificationItem[]>(STORAGE_KEYS.notifications, []);
}

function saveNotifications(items: NotificationItem[]) {
  setStorageValue(STORAGE_KEYS.notifications, JSON.stringify(items.slice(0, 30)));
}

let messageSaveTimer: number | null = null;
function saveConversationMessages(messages: Record<string, Message[]>) {
  if (!hasWindow) return;
  if (messageSaveTimer) window.clearTimeout(messageSaveTimer);
  messageSaveTimer = window.setTimeout(() => {
    setStorageValue(STORAGE_KEYS.conversationMessages, JSON.stringify(messages));
    messageSaveTimer = null;
  }, 300);
}

function mapRawStreamState(state: RawStreamState): StreamState {
  switch (state) {
    case "open":
      return "live";
    case "connecting":
      return "connecting";
    case "reconnecting":
      return "reconnecting";
    case "offline":
      return "offline";
    case "closed":
      return "idle";
    default:
      return "idle";
  }
}

function getRunMode() {
  return localStorage.getItem("astra_run_mode") || "execute_confirm";
}

function createConversation(title?: string): ConversationSummary {
  return {
    id: createId("conv"),
    title: title || "Новый чат",
    updated_at: new Date().toISOString(),
    run_ids: [],
    app_icons: ["blue", "teal"]
  };
}

function ensureMessageLimit(messages: Message[]) {
  if (messages.length <= MESSAGE_LIMIT) return messages;
  return messages.slice(-MESSAGE_LIMIT);
}

function getConversationById(conversations: ConversationSummary[], id: string | null) {
  if (!id) return null;
  return conversations.find((item) => item.id === id) || null;
}

function getConversationIdByRunId(conversations: ConversationSummary[], runId: string | null | undefined) {
  if (!runId) return null;
  const conversation = conversations.find((item) => item.run_ids.includes(runId));
  return conversation ? conversation.id : null;
}

function nextConversationId(conversations: ConversationSummary[], activeId: string | null) {
  if (!conversations.length) return null;
  if (!activeId) return conversations[0].id;
  return conversations.find((item) => item.id === activeId)?.id || conversations[0].id;
}

export type ApiStatus = "idle" | "connecting" | "ready" | "error";
export type StreamState = "idle" | "connecting" | "live" | "reconnecting" | "offline";
export type AuthStatus = "CONNECTED" | "CONNECTING" | "NEED_CONNECT" | "SERVER_UNREACHABLE";

export type LastRequestInfo = {
  method: string | null;
  path: string | null;
  status: number | null;
  detail: string | null;
  ts: string | null;
};

export type ConnectionState = {
  apiReachable: boolean | null;
  authOk: boolean | null;
  lastOkTs: string | null;
};

export type AppStore = {
  apiStatus: ApiStatus;
  apiError: string | null;
  authStatus: AuthStatus;
  authError: string | null;
  lastRequestInfo: LastRequestInfo;
  connectionState: ConnectionState;
  authDiagnostics: {
    baseUrl: string;
    tokenPresent: boolean;
    lastStatus: number | null;
    lastErrorDetail: string | null;
    lastAttemptAt: string | null;
    lastOkAt: string | null;
    lastRequest: string | null;
    authMode: "local" | "strict" | null;
    tokenRequired: boolean | null;
  };
  streamState: StreamState;
  connectionHint: string | null;
  sendError: string | null;
  sending: boolean;
  lastFailedMessage: string | null;
  lastFailedMessageId: string | null;
  lastFailedRunId: string | null;
  sidebarWidth: number;
  activityWidth: number;
  activityOpen: boolean;
  lastSelectedPage: AppPage;
  lastSelectedChatId: string | null;
  density: "low" | "medium" | "high";
  grainEnabled: boolean;
  activityDetailed: boolean;
  defaultActivityOpen: boolean;
  overlayOpen: boolean;
  overlayBehavior: OverlayBehavior;
  overlayCorner: OverlayCorner;
  notifications: NotificationItem[];
  projects: Project[];
  projectId: string | null;
  runs: Run[];
  runMap: Record<string, Run>;
  conversations: ConversationSummary[];
  conversationMessages: Record<string, Message[]>;
  currentRun: Run | null;
  activeRunId: string | null;
  approvals: Approval[];
  events: EventItem[];
  activity: Activity | null;
  memoryItems: UserMemory[];
  memoryLoading: boolean;
  memoryError: string | null;
  reminders: Reminder[];
  remindersLoading: boolean;
  remindersError: string | null;
  bootstrap: () => Promise<void>;
  connectAuth: (mode?: "auto" | "manual") => Promise<boolean>;
  resetAuth: () => Promise<void>;
  regenerateAuth: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  startNewConversation: () => void;
  selectConversation: (conversationId: string | null) => Promise<void>;
  sendMessage: (text: string, options?: { conversationId?: string | null; parentRunId?: string | null }) => Promise<boolean>;
  retrySend: () => Promise<void>;
  retryMessage: (messageId: string) => Promise<void>;
  completeMessageTyping: (conversationId: string, messageId: string) => void;
  requestMore: (messageId: string) => Promise<void>;
  clearConversation: (conversationId: string) => void;
  renameConversation: (conversationId: string, title: string) => void;
  deleteConversation: (conversationId: string) => void;
  exportConversation: (conversationId: string) => string | null;
  openRenameChat: (chatId: string) => void;
  closeRenameChat: () => void;
  renameChatId: string | null;
  setSidebarWidth: (value: number) => void;
  setActivityWidth: (value: number) => void;
  setActivityOpen: (value: boolean) => void;
  setLastSelectedPage: (value: AppPage) => void;
  setLastSelectedChatId: (value: string | null) => void;
  setDensity: (value: "low" | "medium" | "high") => void;
  setGrainEnabled: (value: boolean) => void;
  setActivityDetailed: (value: boolean) => void;
  setDefaultActivityOpen: (value: boolean) => void;
  setOverlayOpen: (value: boolean) => void;
  setOverlayBehavior: (value: OverlayBehavior) => void;
  setOverlayCorner: (value: OverlayCorner) => void;
  addNotification: (item: NotificationItem) => void;
  dismissNotification: (id: string) => void;
  clearNotifications: () => void;
  loadMemory: (query?: string) => Promise<void>;
  deleteMemory: (memoryId: string) => Promise<void>;
  loadReminders: () => Promise<void>;
  createReminder: (payload: { text: string; dueAt: string; delivery?: string }) => Promise<boolean>;
  cancelReminder: (reminderId: string) => Promise<boolean>;
  pauseActiveRun: () => Promise<void>;
  cancelActiveRun: () => Promise<void>;
};

let eventHandle: { disconnect: () => void } | null = null;
let pollTimer: number | null = null;
let refreshTimer: number | null = null;
let refreshInFlight = false;
let refreshQueued = false;
let lastSeq = 0;
let pendingEvents: EventItem[] = [];
let flushRaf: number | null = null;
const postedMarks = new Set<string>();
let autoBootstrapAttempted = false;
let pendingAuthRetry: (() => Promise<void>) | null = null;
let reminderStatusCache = new Map<string, string>();
const notificationTimers = new Map<string, ReturnType<typeof setTimeout>>();
const sendQueue: PendingSendJob[] = [];
const failedSendJobs = new Map<string, PendingSendJob>();
let sendQueueProcessing = false;

function clearNotificationTimer(notificationId: string) {
  const timer = notificationTimers.get(notificationId);
  if (!timer) return;
  clearTimeout(timer);
  notificationTimers.delete(notificationId);
}

function clearAllNotificationTimers() {
  notificationTimers.forEach((timer) => clearTimeout(timer));
  notificationTimers.clear();
}

function notificationTtl(item: NotificationItem): number | null {
  const text = `${item.title || ""} ${item.body || ""}`.toLowerCase();
  if (text.includes("подтверждение") || text.includes("approval")) {
    return null;
  }
  if (item.severity === "error") return NOTIFICATION_TTL_ERROR_MS;
  if (item.severity === "warning") return NOTIFICATION_TTL_WARNING_MS;
  return NOTIFICATION_TTL_MS;
}

function cleanupEventStream() {
  if (eventHandle) {
    eventHandle.disconnect();
    eventHandle = null;
  }
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  if (flushRaf) {
    window.cancelAnimationFrame(flushRaf);
    flushRaf = null;
  }
}

function queueSnapshotRefresh(runId: string, refresh: (id: string) => Promise<void>, delay = 600) {
  if (refreshTimer) return;
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null;
    void refreshSnapshotSafe(runId, refresh);
  }, delay);
}

async function refreshSnapshotSafe(runId: string, refresh: (id: string) => Promise<void>) {
  if (refreshInFlight) {
    refreshQueued = true;
    return;
  }
  refreshInFlight = true;
  try {
    await refresh(runId);
  } finally {
    refreshInFlight = false;
    if (refreshQueued) {
      refreshQueued = false;
      void refreshSnapshotSafe(runId, refresh);
    }
  }
}

function makeCompletionMessage(snapshot: Snapshot) {
  if (snapshot.run.status === "done") {
    const coverage = snapshot.metrics?.coverage;
    if (coverage && typeof coverage.done === "number" && typeof coverage.total === "number") {
      return `Готово. Выполнено шагов: ${coverage.done} из ${coverage.total}.`;
    }
    return "Готово. Выполнение завершено.";
  }
  if (snapshot.run.status === "failed") {
    return "Произошла ошибка при выполнении. Проверьте правую панель.";
  }
  if (snapshot.run.status === "canceled") {
    return "Выполнение остановлено пользователем.";
  }
  return null;
}

export const useAppStore = create<AppStore>((set, get) => {
  const ensureConversationRun = (conversationId: string, runId: string) => {
    const conversations = get().conversations.map((conv) => {
      if (conv.id !== conversationId) return conv;
      if (conv.run_ids.includes(runId)) return conv;
      const run = get().runMap[runId];
      return {
        ...conv,
        run_ids: [...conv.run_ids, runId],
        updated_at: run?.created_at || new Date().toISOString(),
        app_icons: mapRunIcons(run)
      };
    });
    set({ conversations });
    saveConversations(conversations);
  };

  const updateConversationMessages = (conversationId: string, updater: (messages: Message[]) => Message[]) => {
    const map = { ...get().conversationMessages };
    const current = map[conversationId] || [];
    const next = ensureMessageLimit(updater(current));
    map[conversationId] = next;
    set({ conversationMessages: map });
    saveConversationMessages(map);
  };

  const appendMessage = (conversationId: string, message: Message) => {
    updateConversationMessages(conversationId, (messages) => [...messages, message]);
    let conversations = get().conversations.map((conv) =>
      conv.id === conversationId
        ? { ...conv, updated_at: message.ts, app_icons: conv.app_icons.length ? conv.app_icons : ["blue", "teal"] }
        : conv
    );
    conversations = conversations.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
    set({ conversations });
    saveConversations(conversations);
  };

  const replaceMessageRunId = (conversationId: string, messageId: string, runId: string) => {
    updateConversationMessages(conversationId, (messages) =>
      messages.map((item) =>
        item.id === messageId ? { ...item, run_id: runId, delivery_state: "delivered", error_detail: null } : item
      )
    );
  };

  const updateMessage = (conversationId: string, messageId: string, patch: Partial<Message>) => {
    updateConversationMessages(conversationId, (messages) =>
      messages.map((item) => (item.id === messageId ? { ...item, ...patch } : item))
    );
  };

  const getMessage = (conversationId: string, messageId: string): Message | null => {
    const messages = get().conversationMessages[conversationId] || [];
    return messages.find((item) => item.id === messageId) || null;
  };

  const ensureRunMessages = (conversationId: string, snapshot: Snapshot) => {
    const messages = get().conversationMessages[conversationId] || [];
    const hasUser = messages.some((message) => message.run_id === snapshot.run.id && message.role === "user");
    if (!hasUser) {
      appendMessage(conversationId, {
        id: createId("msg"),
        chat_id: conversationId,
        role: "user",
        text: snapshot.run.query_text,
        ts: snapshot.run.created_at || new Date().toISOString(),
        run_id: snapshot.run.id,
        delivery_state: "delivered"
      });
    }
    const planMessage = buildPlanMessage(snapshot.plan || []);
    if (planMessage) {
      const hasPlan = messages.some(
        (message) => message.run_id === snapshot.run.id && message.role === "astra" && message.text.startsWith("План:")
      );
      if (!hasPlan) {
        appendMessage(conversationId, {
          id: createId("msg"),
          chat_id: conversationId,
          role: "astra",
          text: planMessage,
          ts: snapshot.run.created_at || new Date().toISOString(),
          run_id: snapshot.run.id
        });
      }
    }
  };

  const ensureCompletionMessage = (conversationId: string, snapshot: Snapshot) => {
    const key = `${conversationId}:${snapshot.run.id}:${snapshot.run.status}`;
    if (postedMarks.has(key)) return;
    const message = makeCompletionMessage(snapshot);
    if (!message) return;
    postedMarks.add(key);
    appendMessage(conversationId, {
      id: createId("msg"),
      chat_id: conversationId,
      role: "astra",
      text: message,
      ts: new Date().toISOString(),
      run_id: snapshot.run.id
    });
  };

  const ensureApprovalMessage = (conversationId: string, approvals: Approval[]) => {
    approvals
      .filter((item) => item.status === "pending")
      .forEach((approval) => {
        const key = `approval:${approval.id}`;
        if (postedMarks.has(key)) return;
        postedMarks.add(key);
        appendMessage(conversationId, {
          id: createId("msg"),
          chat_id: conversationId,
          role: "astra",
          text: approval.title || "Требуется подтверждение перед продолжением.",
          ts: approval.created_at || new Date().toISOString(),
          run_id: approval.run_id
        });
      });
  };

  const syncAuthDiagnostics = () => {
    const diagnostics = getDiagnostics();
    const parsed = diagnostics.lastRequest ? diagnostics.lastRequest.split(" ") : [];
    const method = parsed.length ? parsed[0] : null;
    const path = parsed.length > 1 ? parsed.slice(1).join(" ") : null;
    const apiReachable =
      typeof diagnostics.lastStatus === "number"
        ? diagnostics.lastStatus >= 200 && diagnostics.lastStatus < 500
        : null;
    const authOk =
      diagnostics.tokenRequired === false
        ? true
        : diagnostics.lastStatus === 401 || diagnostics.lastStatus === 403
          ? false
          : get().authStatus === "CONNECTED"
            ? true
            : null;
    set({
      authDiagnostics: diagnostics,
      lastRequestInfo: {
        method,
        path,
        status: diagnostics.lastStatus,
        detail: diagnostics.lastErrorDetail,
        ts: diagnostics.lastAttemptAt
      },
      connectionState: {
        apiReachable,
        authOk,
        lastOkTs: diagnostics.lastOkAt ?? null
      }
    });
  };

  const setAuthFailure = (message: string, status?: number | null) => {
    setLastError(message, status ?? null);
    set({
      authStatus: "NEED_CONNECT",
      authError: message,
      connectionHint: null,
      sendError: null,
      sending: false
    });
    syncAuthDiagnostics();
  };

  const setServerUnreachable = () => {
    setLastError("Сервер недоступен", null);
    set({
      authStatus: "SERVER_UNREACHABLE",
      authError: "Сервер недоступен",
      apiStatus: "error",
      apiError: "Сервер недоступен",
      connectionHint: null,
      sendError: null,
      sending: false
    });
    syncAuthDiagnostics();
  };

  const loadAfterAuth = async (preloadedProjects?: Project[]) => {
    const projects = preloadedProjects ?? (await listProjects());
    let project = projects[0];
    if (!project) {
      project = await createProject({ name: "Основной", tags: ["default"], settings: {} });
    }
    set({ authStatus: "CONNECTED", authError: null, projects: project ? [project] : projects, projectId: project?.id || null });
    syncAuthDiagnostics();
    await get().refreshRuns();
    await get().loadMemory();
    await get().loadReminders();
    const selectedId = get().lastSelectedChatId;
    const resolved = nextConversationId(get().conversations, selectedId);
    if (resolved) {
      set({ lastSelectedChatId: resolved });
      await get().selectConversation(resolved);
    }
  };

  const removeQueuedJobsForConversation = (conversationId: string) => {
    for (let index = sendQueue.length - 1; index >= 0; index -= 1) {
      if (sendQueue[index].conversationId === conversationId) {
        sendQueue.splice(index, 1);
      }
    }
    failedSendJobs.forEach((job, messageId) => {
      if (job.conversationId === conversationId) {
        failedSendJobs.delete(messageId);
      }
    });
  };

  const queueSendJob = (job: PendingSendJob, front = false) => {
    const existingIndex = sendQueue.findIndex((item) => item.messageId === job.messageId);
    if (existingIndex >= 0) {
      sendQueue.splice(existingIndex, 1);
    }
    if (front) {
      sendQueue.unshift(job);
      return;
    }
    sendQueue.push(job);
  };

  const processSendQueue = async () => {
    if (sendQueueProcessing) return;
    sendQueueProcessing = true;
    try {
      while (sendQueue.length) {
        const job = sendQueue[0];
        const projectId = get().projectId;
        if (!projectId) {
          const errorText = "Не выбран проект для отправки сообщения.";
          updateMessage(job.conversationId, job.messageId, { delivery_state: "failed", error_detail: errorText });
          failedSendJobs.set(job.messageId, job);
          sendQueue.shift();
          set({
            sendError: errorText,
            lastFailedMessage: job.queryText,
            lastFailedMessageId: job.messageId,
            sending: false
          });
          break;
        }

        if (!getMessage(job.conversationId, job.messageId)) {
          failedSendJobs.delete(job.messageId);
          sendQueue.shift();
          continue;
        }

        updateMessage(job.conversationId, job.messageId, { delivery_state: "sending", error_detail: null });
        set({
          sending: true,
          sendError: null,
          lastFailedMessage: null,
          lastFailedMessageId: null,
          lastFailedRunId: null
        });

        const currentConversation = getConversationById(get().conversations, job.conversationId);
        const latestRunId = currentConversation?.run_ids.slice(-1)[0] || null;
        const parentRunId = job.parentRunId || latestRunId;

        let response: RunIntentResponse;
        try {
          response = await runService.createRun(projectId, {
            query_text: job.queryText,
            mode: getRunMode(),
            parent_run_id: parentRunId || undefined
          });
        } catch (err) {
          sendQueue.shift();
          const message = err instanceof Error ? err.message : "Не удалось отправить запрос";
          updateMessage(job.conversationId, job.messageId, { delivery_state: "failed", error_detail: message });
          failedSendJobs.set(job.messageId, job);
          set({ lastFailedMessage: job.queryText, lastFailedMessageId: job.messageId });
          if (isAuthError(err)) {
            pendingAuthRetry = async () => {
              await get().retryMessage(job.messageId);
            };
            setAuthFailure(err.detail || err.message || "Требуется подключение");
          } else if (isNetworkError(err)) {
            setServerUnreachable();
          } else {
            set({ sendError: message });
          }
          break;
        }

        sendQueue.shift();

        if (!response.run) {
          const message = "Не удалось создать чат";
          updateMessage(job.conversationId, job.messageId, { delivery_state: "failed", error_detail: message });
          failedSendJobs.set(job.messageId, job);
          set({
            sendError: message,
            lastFailedMessage: job.queryText,
            lastFailedMessageId: job.messageId
          });
          break;
        }

        failedSendJobs.delete(job.messageId);
        const run = response.run;
        replaceMessageRunId(job.conversationId, job.messageId, run.id);
        const runMap = { ...get().runMap, [run.id]: run };
        let conversations = get().conversations.map((conv) => {
          if (conv.id !== job.conversationId) return conv;
          const nextTitle = conv.title === "Новый чат" ? buildConversationTitle(job.titleSeed) : conv.title;
          const runIds = conv.run_ids.includes(run.id) ? conv.run_ids : [...conv.run_ids, run.id];
          return {
            ...conv,
            title: nextTitle,
            run_ids: runIds,
            updated_at: run.created_at || job.createdAt,
            app_icons: mapRunIcons(run)
          };
        });
        conversations = conversations.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
        set({
          runMap,
          conversations,
          activeRunId: run.id,
          currentRun: run,
          lastSelectedChatId: get().lastSelectedChatId || job.conversationId
        });
        saveConversations(conversations);

        const appendAssistantReply = (text: string, typing = true) => {
          const userName = nameFromMeta(run.meta);
          appendMessage(job.conversationId, {
            id: createId("msg"),
            chat_id: job.conversationId,
            role: "astra",
            text: withName(text, userName),
            ts: new Date().toISOString(),
            run_id: run.id,
            typing
          });
        };

        if (response.kind === "clarify") {
          const questions = response.questions?.filter(Boolean) || [];
          appendAssistantReply(questions.join("\n") || PHRASES.clarifyFallback);
        }
        if (response.kind === "chat") {
          appendAssistantReply(response.chat_response || PHRASES.chatFallback);
        }
        if (response.kind === "act") {
          appendAssistantReply(PHRASES.actStart, false);
        }

        if (get().lastSelectedChatId === job.conversationId) {
          await get().selectConversation(job.conversationId);
        }

        if (response.kind === "act") {
          try {
            await runService.startRun(run.id);
          } catch (err) {
            const message = err instanceof Error ? err.message : "Не удалось запустить выполнение";
            set({ sendError: message, lastFailedRunId: run.id });
          }
        }
      }
    } finally {
      sendQueueProcessing = false;
      set({ sending: false });
    }
  };

  const startPolling = (runId: string, refresh: (id: string) => Promise<void>) => {
    if (pollTimer) return;
    pollTimer = window.setInterval(() => {
      void refreshSnapshotSafe(runId, refresh);
    }, POLL_INTERVAL_MS);
  };

  const stopPolling = () => {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const initialDiagnostics = getDiagnostics();
  const initialParts = initialDiagnostics.lastRequest ? initialDiagnostics.lastRequest.split(" ") : [];
  const initialRequestInfo: LastRequestInfo = {
    method: initialParts.length ? initialParts[0] : null,
    path: initialParts.length > 1 ? initialParts.slice(1).join(" ") : null,
    status: initialDiagnostics.lastStatus,
    detail: initialDiagnostics.lastErrorDetail,
    ts: initialDiagnostics.lastAttemptAt
  };
  const initialConnectionState: ConnectionState = {
    apiReachable:
      typeof initialDiagnostics.lastStatus === "number"
        ? initialDiagnostics.lastStatus >= 200 && initialDiagnostics.lastStatus < 500
        : null,
    authOk:
      initialDiagnostics.tokenRequired === false
        ? true
        : initialDiagnostics.lastStatus === 401 || initialDiagnostics.lastStatus === 403
          ? false
          : null,
    lastOkTs: initialDiagnostics.lastOkAt ?? null
  };

  return {
    apiStatus: "idle",
    apiError: null,
    authStatus: "CONNECTING",
    authError: null,
    lastRequestInfo: initialRequestInfo,
    connectionState: initialConnectionState,
    authDiagnostics: initialDiagnostics,
    streamState: "idle",
    connectionHint: null,
    sendError: null,
    sending: false,
    lastFailedMessage: null,
    lastFailedMessageId: null,
    lastFailedRunId: null,
    sidebarWidth: clamp(loadNumber(STORAGE_KEYS.sidebarWidth, DEFAULT_SIDEBAR_WIDTH), 220, 420),
    activityWidth: clamp(loadNumber(STORAGE_KEYS.activityWidth, DEFAULT_ACTIVITY_WIDTH), 300, 520),
    activityOpen: loadBoolean(STORAGE_KEYS.activityOpen, loadBoolean(STORAGE_KEYS.defaultActivityOpen, true)),
    lastSelectedPage: loadString(STORAGE_KEYS.lastSelectedPage, "chat") as AppPage,
    lastSelectedChatId: loadString(STORAGE_KEYS.lastSelectedChatId, "") || null,
    density: (loadString(STORAGE_KEYS.density, "medium") as "low" | "medium" | "high") || "medium",
    grainEnabled: loadBoolean(STORAGE_KEYS.grain, true),
    activityDetailed: loadBoolean(STORAGE_KEYS.activityDetailed, false),
    defaultActivityOpen: loadBoolean(STORAGE_KEYS.defaultActivityOpen, true),
    overlayOpen: loadBoolean(STORAGE_KEYS.overlayOpen, false),
    overlayBehavior: loadString(STORAGE_KEYS.overlayBehavior, "mini") as OverlayBehavior,
    overlayCorner: loadString(STORAGE_KEYS.overlayCorner, "top-right") as OverlayCorner,
    notifications: loadNotifications(),
    projects: [],
    projectId: null,
    runs: [],
    runMap: {},
    conversations: loadConversations(),
    conversationMessages: loadConversationMessages(),
    currentRun: null,
    activeRunId: null,
    approvals: [],
    events: [],
    activity: null,
    memoryItems: [],
    memoryLoading: false,
    memoryError: null,
    reminders: [],
    remindersLoading: false,
    remindersError: null,
    renameChatId: null,
    bootstrap: async () => {
      set({ apiStatus: "connecting", apiError: null, connectionHint: null });
      try {
        await checkStatus();
        set({ apiStatus: "ready" });

        set({ authStatus: "CONNECTING", authError: null });

        try {
          const projects = await listProjects();
          await loadAfterAuth(projects);
          return;
        } catch (err) {
          if (isAuthError(err)) {
            if (!autoBootstrapAttempted) {
              autoBootstrapAttempted = true;
              const connected = await get().connectAuth("auto");
              if (!connected) return;
              return;
            }
            setAuthFailure(err.detail || err.message || "Не удалось подключиться", err.status);
            return;
          }
          if (isNetworkError(err)) {
            setServerUnreachable();
            return;
          }
          const message = err instanceof Error ? err.message : "Не удалось подключиться";
          set({ apiStatus: "error", apiError: message });
          return;
        }
      } catch (err) {
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        if (isAuthError(err)) {
          if (!autoBootstrapAttempted) {
            autoBootstrapAttempted = true;
            const connected = await get().connectAuth("auto");
            if (!connected) return;
            return;
          }
          setAuthFailure(err.detail || err.message || "Не удалось подключиться", err.status);
          return;
        }
        const message = err instanceof Error ? err.message : "Не удалось подключиться";
        set({ apiStatus: "error", apiError: message });
      }
    },
    connectAuth: async (mode = "manual") => {
      const previousStatus = get().authStatus;
      if (previousStatus === "CONNECTING") return false;
      set({ authStatus: "CONNECTING", authError: null, sendError: null });
      const reason = mode === "manual" && previousStatus === "NEED_CONNECT" ? "auth_error" : mode;
      try {
        await connectController(reason as "auto" | "manual" | "auth_error");
        const status = await checkStatus();
        if (status.token_required === false) {
          const projects = await listProjects();
          await loadAfterAuth(projects);
        } else {
          await loadAfterAuth();
        }
        if (pendingAuthRetry) {
          const action = pendingAuthRetry;
          pendingAuthRetry = null;
          await action();
        }
        syncAuthDiagnostics();
        return true;
      } catch (err) {
        if (isNetworkError(err)) {
          setServerUnreachable();
          return false;
        }
        const message = err instanceof ApiError ? err.detail || err.message : "Требуется подключение";
        setAuthFailure(message, err instanceof ApiError ? err.status : null);
        return false;
      }
    },
    resetAuth: async () => {
      clearToken();
      syncAuthDiagnostics();
      await get().connectAuth("manual");
    },
    regenerateAuth: async () => {
      set({ authStatus: "CONNECTING", authError: null, sendError: null });
      try {
        await regenerateToken();
        await get().connectAuth("manual");
      } catch (err) {
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        const message = err instanceof ApiError ? err.detail || err.message : "Не удалось обновить токен";
        setAuthFailure(message, err instanceof ApiError ? err.status : null);
      }
    },
    refreshRuns: async () => {
      const projectId = get().projectId;
      if (!projectId) return;
      try {
        const runs = await listRuns(projectId, RUNS_LIMIT);
        const runMap = runs.reduce<Record<string, Run>>((acc, run) => {
          acc[run.id] = run;
          return acc;
        }, {});
        let conversations = get().conversations.map((conv) => ({ ...conv, run_ids: [...conv.run_ids] }));
        const stored = conversations.length > 0;
        const hiddenRuns = new Set(loadJSON<string[]>(STORAGE_KEYS.legacyHiddenRuns, []));
        const titleOverrides = loadJSON<Record<string, string>>(STORAGE_KEYS.legacyTitleOverrides, {});

        if (!stored) {
          const runToConversation = new Map<string, ConversationSummary>();
          const ordered = [...runs].sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
          const seeded: ConversationSummary[] = [];
          ordered.forEach((run) => {
            if (hiddenRuns.has(run.id)) return;
            const parentId = run.parent_run_id || "";
            const parentConv = parentId ? runToConversation.get(parentId) : null;
            if (parentConv) {
              parentConv.run_ids.push(run.id);
              parentConv.updated_at = run.created_at || parentConv.updated_at;
              parentConv.app_icons = mapRunIcons(run);
              runToConversation.set(run.id, parentConv);
              return;
            }
            const title = titleOverrides[run.id] || buildConversationTitle(run.query_text);
            const conv: ConversationSummary = {
              id: createId("conv"),
              title,
              updated_at: run.created_at || new Date().toISOString(),
              run_ids: [run.id],
              app_icons: mapRunIcons(run)
            };
            seeded.push(conv);
            runToConversation.set(run.id, conv);
          });
          conversations = seeded;
        } else {
          const existingRunIds = new Set(conversations.flatMap((conv) => conv.run_ids));
          const sorted = [...runs].sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
          const extra: ConversationSummary[] = [];
          sorted.forEach((run) => {
            if (existingRunIds.has(run.id) || hiddenRuns.has(run.id)) return;
            const parentConv = run.parent_run_id
              ? conversations.find((conv) => conv.run_ids.includes(run.parent_run_id as string))
              : null;
            if (parentConv) {
              parentConv.run_ids.push(run.id);
              parentConv.updated_at = run.created_at || parentConv.updated_at;
              parentConv.app_icons = mapRunIcons(run);
              return;
            }
            extra.push({
              id: createId("conv"),
              title: titleOverrides[run.id] || buildConversationTitle(run.query_text),
              updated_at: run.created_at || new Date().toISOString(),
              run_ids: [run.id],
              app_icons: mapRunIcons(run)
            });
          });
          if (extra.length) {
            conversations = [...extra, ...conversations];
          }
        }

        conversations = [...conversations].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
        if (conversations.length > CONVERSATION_LIMIT) {
          conversations = conversations.slice(0, CONVERSATION_LIMIT);
        }
        set({ runs, runMap, conversations });
        saveConversations(conversations);
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        const message = err instanceof Error ? err.message : "Не удалось загрузить чаты";
        set({ apiError: message, apiStatus: "error" });
      }
    },
    startNewConversation: () => {
      cleanupEventStream();
      pendingEvents = [];
      const conversation = createConversation();
      const conversations = [conversation, ...get().conversations];
      set({
        conversations,
        lastSelectedChatId: conversation.id,
        activeRunId: null,
        currentRun: null,
        events: [],
        approvals: [],
        activity: null,
        streamState: "idle",
        connectionHint: null
      });
      saveConversations(conversations);
    },
    selectConversation: async (conversationId) => {
      cleanupEventStream();
      lastSeq = 0;
      pendingEvents = [];
      set({ events: [], approvals: [], currentRun: null, activity: null, streamState: "idle", activeRunId: null });
      set({ lastSelectedChatId: conversationId });
      if (!conversationId) return;
      const conversation = getConversationById(get().conversations, conversationId);
      const runId = conversation?.run_ids.slice(-1)[0] || null;
      if (!runId) return;
      set({ activeRunId: runId });
      const refreshSnapshot = async (targetId: string) => {
        const snapshot = await runService.fetchSnapshot(targetId);
        const result = mergeEvents(get().events, snapshot.last_events || [], EVENT_BUFFER_LIMIT);
        lastSeq = result.lastSeq;
        const activity = activityFromSnapshot(snapshot, result.events);
        const runMap = { ...get().runMap, [snapshot.run.id]: snapshot.run };
        set({
          currentRun: snapshot.run,
          approvals: snapshot.approvals || [],
          events: result.events,
          activity,
          runMap
        });
        ensureConversationRun(conversationId, snapshot.run.id);
        ensureRunMessages(conversationId, snapshot);
        ensureApprovalMessage(conversationId, snapshot.approvals || []);
        ensureCompletionMessage(conversationId, snapshot);
      };

      try {
        await refreshSnapshot(runId);
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        const message = err instanceof Error ? err.message : "Не удалось загрузить чат";
        set({ connectionHint: message });
      }

      const safeToken = getToken();
      if (!safeToken) {
        setAuthFailure("Требуется подключение");
        return;
      }
      const onEvents = (incoming: EventItem[]) => {
        pendingEvents = pendingEvents.concat(incoming);
        if (flushRaf) return;
          flushRaf = window.requestAnimationFrame(() => {
            flushRaf = null;
            const batch = pendingEvents;
            pendingEvents = [];
            if (!batch.length) return;
            batch.forEach((event) => {
              const notification = notificationFromReminderEvent(event);
              if (notification) {
                get().addNotification(notification);
              }
              if (event.type === "memory_saved") {
                const key = `memory_saved:${event.id}`;
                if (postedMarks.has(key)) return;
                postedMarks.add(key);
                const payload = event.payload || {};
                const origin = typeof payload.origin === "string" ? payload.origin : "";
                if (origin === "auto") return;
                const conversationId =
                  getConversationIdByRunId(get().conversations, event.run_id) || get().lastSelectedChatId;
                if (!conversationId) return;
                const title = typeof payload.title === "string" ? payload.title : "Запись сохранена";
                appendMessage(conversationId, {
                  id: createId("msg"),
                  chat_id: conversationId,
                  role: "astra",
                  text: `Запомнил: ${title}`,
                  ts: new Date().toISOString(),
                  run_id: event.run_id
                });
              }
            });
            const result = mergeEvents(get().events, batch, EVENT_BUFFER_LIMIT);
            lastSeq = result.lastSeq;
            set({ events: result.events });
          const delay = batch.some((evt) =>
            ["run_done", "run_failed", "run_canceled", "approval_requested", "step_paused_for_approval"].includes(evt.type)
          )
            ? 0
            : batch.some((evt) => evt.type === "task_progress")
              ? 1200
              : 700;
          queueSnapshotRefresh(runId, refreshSnapshot, delay);
        });
      };

      eventHandle = runService.openEventStream(runId, {
        token: safeToken,
        lastEventId: lastSeq,
        eventTypes: EVENT_TYPES,
        onEvent: (evt) => onEvents([evt]),
        onStateChange: (state) => {
          const mapped = mapRawStreamState(state);
          set({ streamState: mapped });
          if (mapped === "live") {
            stopPolling();
          } else if (mapped === "reconnecting" || mapped === "offline") {
            startPolling(runId, refreshSnapshot);
          }
        },
        onError: (message) => set({ connectionHint: message }),
        onReconnect: () => {
          void refreshSnapshotSafe(runId, refreshSnapshot);
        },
        getLastEventId: () => lastSeq
      });
    },
    sendMessage: async (text, options) => {
      const projectId = get().projectId;
      if (!projectId) return false;
      const queryText = text;
      const queryTrimmed = text.trim();
      if (!queryTrimmed) return false;

      let conversationId = options?.conversationId ?? get().lastSelectedChatId;
      if (!conversationId) {
        const conversation = createConversation();
        conversationId = conversation.id;
        const conversations = [conversation, ...get().conversations];
        set({ conversations, lastSelectedChatId: conversationId });
        saveConversations(conversations);
      }

      const currentConversation = getConversationById(get().conversations, conversationId);
      const lastRunId = currentConversation?.run_ids.slice(-1)[0] || null;
      const parentRunId = options?.parentRunId ?? lastRunId;
      const messageId = createId("msg");
      const createdAt = new Date().toISOString();

      appendMessage(conversationId, {
        id: messageId,
        chat_id: conversationId,
        role: "user",
        text: queryText,
        ts: createdAt,
        delivery_state: "queued",
        error_detail: null
      });
      set({ sendError: null, lastFailedMessage: null, lastFailedMessageId: null, lastFailedRunId: null });

      queueSendJob({
        messageId,
        conversationId,
        queryText,
        titleSeed: queryTrimmed,
        parentRunId,
        createdAt
      });
      void processSendQueue();
      return true;
    },
    retrySend: async () => {
      const failedMessageId = get().lastFailedMessageId;
      const failedRunId = get().lastFailedRunId;
      if (failedMessageId) {
        await get().retryMessage(failedMessageId);
        return;
      }
      if (failedRunId) {
        try {
          await runService.startRun(failedRunId);
          set({ sendError: null, lastFailedRunId: null });
        } catch (err) {
          const message = err instanceof Error ? err.message : "Не удалось запустить выполнение";
          set({ sendError: message });
        }
      }
    },
    retryMessage: async (messageId) => {
      let job = failedSendJobs.get(messageId) || null;
      if (!job) {
        const entries = Object.entries(get().conversationMessages);
        for (const [conversationId, messages] of entries) {
          const source = messages.find((item) => item.id === messageId && item.role === "user");
          if (!source) continue;
          const conversation = getConversationById(get().conversations, conversationId);
          const runId = conversation?.run_ids.slice(-1)[0] || null;
          job = {
            messageId,
            conversationId,
            queryText: source.text,
            titleSeed: source.text.trim() || "Новый чат",
            parentRunId: runId,
            createdAt: source.ts || new Date().toISOString()
          };
          break;
        }
      }
      if (!job) return;
      failedSendJobs.delete(messageId);
      updateMessage(job.conversationId, messageId, { delivery_state: "queued", error_detail: null });
      set({ sendError: null, lastFailedMessage: null, lastFailedMessageId: null });
      queueSendJob(job, true);
      void processSendQueue();
    },
    completeMessageTyping: (conversationId, messageId) => {
      updateMessage(conversationId, messageId, { typing: false });
    },
    requestMore: async (messageId) => {
      const conversationId = get().lastSelectedChatId;
      if (!conversationId) return;
      const messages = get().conversationMessages[conversationId] || [];
      const source = messages.find((message) => message.id === messageId);
      const hint = source?.text ? `\nКонтекст: ${source.text.slice(0, 200)}` : "";
      const parentRunId = get().activeRunId;
      await get().sendMessage(`Раскрой подробнее по предыдущему ответу.${hint}`, {
        conversationId,
        parentRunId
      });
    },
    clearConversation: (conversationId) => {
      removeQueuedJobsForConversation(conversationId);
      const conversations = get().conversations.map((conv) =>
        conv.id === conversationId ? { ...conv, run_ids: [] } : conv
      );
      const conversationMessages = { ...get().conversationMessages };
      conversationMessages[conversationId] = [];
      set({
        conversations,
        conversationMessages,
        activeRunId: null,
        currentRun: null,
        approvals: [],
        events: [],
        activity: null,
        streamState: "idle",
        connectionHint: null,
        sendError: null,
        lastFailedMessage: null,
        lastFailedMessageId: null,
        lastFailedRunId: null
      });
      saveConversations(conversations);
      saveConversationMessages(conversationMessages);
      cleanupEventStream();
    },
    renameConversation: (conversationId, title) => {
      if (!title.trim()) return;
      const conversations = get().conversations.map((conv) =>
        conv.id === conversationId ? { ...conv, title: title.trim() } : conv
      );
      set({ conversations });
      saveConversations(conversations);
    },
    deleteConversation: (conversationId) => {
      removeQueuedJobsForConversation(conversationId);
      const conversations = get().conversations.filter((conv) => conv.id !== conversationId);
      const conversationMessages = { ...get().conversationMessages };
      delete conversationMessages[conversationId];
      const nextId = nextConversationId(conversations, get().lastSelectedChatId === conversationId ? null : get().lastSelectedChatId);
      set({
        conversations,
        conversationMessages,
        lastSelectedChatId: nextId,
        activeRunId: null,
        currentRun: null,
        approvals: [],
        events: [],
        activity: null,
        streamState: "idle",
        sendError: null,
        lastFailedMessage: null,
        lastFailedMessageId: null,
        lastFailedRunId: null
      });
      saveConversations(conversations);
      saveConversationMessages(conversationMessages);
      if (nextId) {
        void get().selectConversation(nextId);
      } else {
        cleanupEventStream();
      }
    },
    exportConversation: (conversationId) => {
      const conversation = getConversationById(get().conversations, conversationId);
      if (!conversation) return null;
      const payload = {
        ...conversation,
        messages: get().conversationMessages[conversationId] || []
      };
      return JSON.stringify(payload, null, 2);
    },
    openRenameChat: (chatId) => set({ renameChatId: chatId }),
    closeRenameChat: () => set({ renameChatId: null }),
    setSidebarWidth: (value) => set({ sidebarWidth: clamp(value, 220, 420) }),
    setActivityWidth: (value) => set({ activityWidth: clamp(value, 300, 520) }),
    setActivityOpen: (value) => set({ activityOpen: value }),
    setLastSelectedPage: (value) => set({ lastSelectedPage: value }),
    setLastSelectedChatId: (value) => set({ lastSelectedChatId: value }),
    setDensity: (value) => set({ density: value }),
    setGrainEnabled: (value) => set({ grainEnabled: value }),
    setActivityDetailed: (value) => set({ activityDetailed: value }),
    setDefaultActivityOpen: (value) => set({ defaultActivityOpen: value, activityOpen: value }),
    setOverlayOpen: (value) => set({ overlayOpen: value }),
    setOverlayBehavior: (value) => set({ overlayBehavior: value }),
    setOverlayCorner: (value) => set({ overlayCorner: value }),
    addNotification: (item) => {
      if (get().notifications.some((existing) => existing.id === item.id)) {
        return;
      }
      set((state) => {
        const next = [item, ...state.notifications].slice(0, 30);
        saveNotifications(next);
        return { notifications: next };
      });
      const ids = new Set(get().notifications.map((entry) => entry.id));
      notificationTimers.forEach((_timer, id) => {
        if (!ids.has(id)) {
          clearNotificationTimer(id);
        }
      });
      const ttl = notificationTtl(item);
      clearNotificationTimer(item.id);
      if (ttl === null) return;
      const timer = setTimeout(() => {
        get().dismissNotification(item.id);
      }, ttl);
      notificationTimers.set(item.id, timer);
    },
    dismissNotification: (id) => {
      clearNotificationTimer(id);
      set((state) => {
        const next = state.notifications.filter((item) => item.id !== id);
        saveNotifications(next);
        return { notifications: next };
      });
    },
    clearNotifications: () => {
      clearAllNotificationTimers();
      saveNotifications([]);
      set({ notifications: [] });
    },
    loadMemory: async (query) => {
      try {
        set({ memoryLoading: true, memoryError: null });
        const items = await listUserMemory(query || "");
        set({ memoryItems: items, memoryLoading: false });
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          set({ memoryLoading: false });
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          set({ memoryLoading: false });
          return;
        }
        set({ memoryLoading: false, memoryError: "Не удалось загрузить память" });
      }
    },
    deleteMemory: async (memoryId) => {
      try {
        await deleteUserMemory(memoryId);
        await get().loadMemory();
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        set({ memoryError: "Не удалось удалить запись" });
      }
    },
    loadReminders: async () => {
      try {
        set({ remindersLoading: true, remindersError: null });
        const items = await listReminders("", 200);
        const nextCache = new Map<string, string>();
        const notifications: NotificationItem[] = [];
        items.forEach((item) => {
          nextCache.set(item.id, item.status);
          const previous = reminderStatusCache.get(item.id);
          if (!previous) return;
          if (previous === item.status) return;
          if (item.status === "sent" || item.status === "failed") {
            notifications.push({
              id: `reminder-${item.id}-${item.status}`,
              ts: new Date().toISOString(),
              title: item.status === "sent" ? "Напоминание отправлено" : "Ошибка напоминания",
              body: item.text,
              severity: item.status === "failed" ? "error" : "success"
            });
          }
        });
        reminderStatusCache = nextCache;
        set({ reminders: items, remindersLoading: false });
        notifications.forEach((notification) => get().addNotification(notification));
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          set({ remindersLoading: false });
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          set({ remindersLoading: false });
          return;
        }
        set({ remindersLoading: false, remindersError: "Не удалось загрузить напоминания" });
      }
    },
    createReminder: async (payload) => {
      try {
        const result = await createReminder({
          due_at: payload.dueAt,
          text: payload.text,
          delivery: payload.delivery,
          source: "ui"
        });
        get().addNotification({
          id: `reminder-created-${result.id}`,
          ts: new Date().toISOString(),
          title: "Напоминание создано",
          body: result.text,
          severity: "info"
        });
        await get().loadReminders();
        return true;
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return false;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return false;
        }
        set({ remindersError: "Не удалось создать напоминание" });
        return false;
      }
    },
    cancelReminder: async (reminderId) => {
      try {
        const result = await cancelReminder(reminderId);
        get().addNotification({
          id: `reminder-cancelled-${result.id}`,
          ts: new Date().toISOString(),
          title: "Напоминание отменено",
          body: result.text,
          severity: "warning"
        });
        await get().loadReminders();
        return true;
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return false;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return false;
        }
        set({ remindersError: "Не удалось отменить напоминание" });
        return false;
      }
    },
    pauseActiveRun: async () => {
      const runId = get().activeRunId;
      if (!runId) return;
      try {
        await pauseRun(runId);
        await get().selectConversation(get().lastSelectedChatId);
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        set({ connectionHint: "Не удалось поставить на паузу" });
      }
    },
    cancelActiveRun: async () => {
      const runId = get().activeRunId;
      if (!runId) return;
      try {
        await cancelRun(runId);
        await get().selectConversation(get().lastSelectedChatId);
      } catch (err) {
        if (isAuthError(err)) {
          setAuthFailure(err.detail || err.message || "Требуется подключение");
          return;
        }
        if (isNetworkError(err)) {
          setServerUnreachable();
          return;
        }
        set({ connectionHint: "Не удалось остановить" });
      }
    }
  };
});

if (hasWindow) {
  useAppStore.subscribe((state, prevState) => {
    if (state.sidebarWidth !== prevState.sidebarWidth) {
      setStorageValue(STORAGE_KEYS.sidebarWidth, String(state.sidebarWidth));
    }
    if (state.activityWidth !== prevState.activityWidth) {
      setStorageValue(STORAGE_KEYS.activityWidth, String(state.activityWidth));
    }
    if (state.activityOpen !== prevState.activityOpen) {
      setStorageValue(STORAGE_KEYS.activityOpen, String(state.activityOpen));
    }
    if (state.lastSelectedPage !== prevState.lastSelectedPage) {
      setStorageValue(STORAGE_KEYS.lastSelectedPage, state.lastSelectedPage);
    }
    if (state.lastSelectedChatId !== prevState.lastSelectedChatId) {
      setStorageValue(STORAGE_KEYS.lastSelectedChatId, state.lastSelectedChatId ?? "");
    }
    if (state.density !== prevState.density) {
      setStorageValue(STORAGE_KEYS.density, state.density);
    }
    if (state.grainEnabled !== prevState.grainEnabled) {
      setStorageValue(STORAGE_KEYS.grain, String(state.grainEnabled));
    }
    if (state.activityDetailed !== prevState.activityDetailed) {
      setStorageValue(STORAGE_KEYS.activityDetailed, String(state.activityDetailed));
    }
    if (state.defaultActivityOpen !== prevState.defaultActivityOpen) {
      setStorageValue(STORAGE_KEYS.defaultActivityOpen, String(state.defaultActivityOpen));
    }
    if (state.overlayOpen !== prevState.overlayOpen) {
      setStorageValue(STORAGE_KEYS.overlayOpen, String(state.overlayOpen));
    }
    if (state.overlayBehavior !== prevState.overlayBehavior) {
      setStorageValue(STORAGE_KEYS.overlayBehavior, state.overlayBehavior);
    }
    if (state.overlayCorner !== prevState.overlayCorner) {
      setStorageValue(STORAGE_KEYS.overlayCorner, state.overlayCorner);
    }
  });
}
