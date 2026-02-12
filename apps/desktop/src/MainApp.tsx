import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/tauri";
import { appWindow } from "@tauri-apps/api/window";
import {
  apiBase,
  listProjects,
  createProject,
  listRuns,
  createRun,
  createPlan,
  startRun,
  cancelRun,
  updateProject,
  getSnapshot,
  initAuth,
  checkApiStatus,
  getSessionToken,
  checkPermissions,
  storeOpenAIKeyLocal,
  getLocalOpenAIStatus,
  approve,
  reject,
  listUserMemory,
  deleteUserMemory,
  pinUserMemory,
  unpinUserMemory
} from "./api";
import SettingsPanel from "./ui/SettingsPanel";
import MemoryPanel from "./ui/MemoryPanel";
import { mergeEvents, statusTone } from "./ui/utils";
import type {
  Approval,
  EventItem,
  PlanStep,
  Project,
  ProjectSettings,
  Run,
  RunIntentResponse,
  SnapshotMetrics,
  Task,
  UserMemory
} from "./types";

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

const MODE_OPTIONS = [
  { value: "plan_only", label: "Только план" },
  { value: "research", label: "Исследование" },
  { value: "execute_confirm", label: "Выполнение с подтверждением" },
  { value: "autopilot_safe", label: "Автопилот (безопасный)" }
];

const RUN_MODE_KEY = "astra_run_mode";
const LAST_PROJECT_KEY = "astra_last_project_id";
const LAST_RUN_KEY = "astra_last_run_id";
const OVERLAY_MODE_KEY = "astra_overlay_mode";
const EVENT_BUFFER_LIMIT = 600;
const EVENT_PAGE_SIZE = 140;
const RUNS_LIMIT = 80;
const POLL_INTERVAL_MS = 5000;

const STATUS_LABELS: Record<string, string> = {
  created: "Ожидание",
  queued: "Ожидание",
  planning: "Планирование",
  running: "В работе",
  paused: "Пауза",
  waiting_approval: "Ожидает подтверждение",
  waiting_confirm: "Ожидает подтверждение",
  done: "Готово",
  failed: "Ошибка",
  canceled: "Отменено"
};

type PermissionsStatus = {
  screen_recording?: boolean;
  accessibility?: boolean;
  message?: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  ts?: number;
  tone?: "info" | "warn" | "error";
};

type InspectorTab = "steps" | "events" | "approvals" | "metrics";

type RightPanel = "inspector" | "memory" | "settings" | "closed";

function nowId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function formatTime(ts?: number) {
  if (!ts) return "";
  const date = new Date(ts);
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function statusLabel(status?: string | null) {
  if (!status) return "—";
  return STATUS_LABELS[status] || status;
}

function shortText(value: string, limit: number) {
  if (value.length <= limit) return value;
  return `${value.slice(0, limit)}…`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function extractProvider(payload?: Record<string, unknown> | null) {
  if (!payload) return null;
  const raw =
    (typeof payload.provider === "string" ? payload.provider : null) ||
    (typeof payload.route === "string" ? payload.route : null);
  if (!raw) return null;
  return raw.toLowerCase().includes("cloud") ? "cloud" : raw.toLowerCase().includes("local") ? "local" : raw;
}

export default function MainApp() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || null,
    [projects, selectedProjectId]
  );
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [metrics, setMetrics] = useState<SnapshotMetrics | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [queryText, setQueryText] = useState("");
  const [mode, setMode] = useState<string>(() => localStorage.getItem(RUN_MODE_KEY) || "execute_confirm");
  const [overlayMode, setOverlayMode] = useState<"auto" | "pinned" | "off">(() => {
    const stored = localStorage.getItem(OVERLAY_MODE_KEY);
    return stored === "pinned" || stored === "off" ? stored : "auto";
  });
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [modelName, setModelName] = useState("gpt-4.1");
  const [rightPanel, setRightPanel] = useState<RightPanel>("inspector");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("steps");
  const [eventLimit, setEventLimit] = useState(EVENT_PAGE_SIZE);
  const [eventSearch, setEventSearch] = useState("");
  const [runSearch, setRunSearch] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryItems, setMemoryItems] = useState<UserMemory[]>([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(null);
  const [openaiKey, setOpenaiKey] = useState("");
  const [keyStored, setKeyStored] = useState(false);
  const [savingKey, setSavingKey] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState<{ text: string; tone: "success" | "error" | "info" } | null>(null);
  const [permissions, setPermissions] = useState<PermissionsStatus | null>(null);
  const [streamState, setStreamState] = useState<"idle" | "live" | "reconnecting" | "polling">("idle");

  const eventsRef = useRef<EventItem[]>([]);
  const lastSeqRef = useRef<number>(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const refreshInFlight = useRef(false);
  const refreshQueued = useRef(false);
  const refreshTimerRef = useRef<number | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);

  const pendingApprovals = useMemo(() => approvals.filter((a) => a.status === "pending"), [approvals]);
  const visibleApproval = pendingApprovals[0] || null;

  const activeStepId = useMemo(() => {
    const runningTask = tasks.find((task) => task.status === "running");
    return runningTask?.plan_step_id || null;
  }, [tasks]);

  const providerStats = useMemo(() => {
    let local = 0;
    let cloud = 0;
    let last: string | null = null;
    for (const event of events) {
      if (event.type !== "llm_provider_used" && event.type !== "llm_route_decided") continue;
      const provider = extractProvider(event.payload || null);
      if (!provider) continue;
      last = provider;
      if (provider === "local") local += 1;
      if (provider === "cloud") cloud += 1;
    }
    return { local, cloud, last };
  }, [events]);

  const errorCount = useMemo(() => {
    return events.filter((event) => event.level === "error" || event.type.includes("failed")).length;
  }, [events]);

  const pauseCount = useMemo(() => {
    return events.filter((event) => event.type.includes("paused") || event.type.includes("waiting")).length;
  }, [events]);

  const stepStats = useMemo(() => {
    const total = plan.length;
    const done = plan.filter((step) => step.status === "done").length;
    const failed = plan.filter((step) => step.status === "failed").length;
    return { total, done, failed };
  }, [plan]);

  const filteredEvents = useMemo(() => {
    const query = eventSearch.trim().toLowerCase();
    return events.filter((event) => {
      if (errorsOnly && event.level !== "error" && !event.type.includes("failed")) return false;
      if (!query) return true;
      const hay = `${event.type} ${event.message || ""}`.toLowerCase();
      return hay.includes(query);
    });
  }, [events, eventSearch, errorsOnly]);

  const visibleEvents = useMemo(() => {
    const slice = filteredEvents.slice(-eventLimit);
    return [...slice].reverse();
  }, [filteredEvents, eventLimit]);

  const runStatus = run?.status || "idle";
  const runStatusLabel = statusLabel(runStatus);
  const statusToneValue = statusTone(runStatus);
  const overlayActive =
    runStatus === "running" || runStatus === "paused" || runStatus.includes("waiting") || pendingApprovals.length > 0;
  const agentStatus = visibleApproval
    ? "Нужен ответ"
    : runStatus === "running"
      ? "Выполняет"
      : runStatus === "paused"
        ? "Пауза"
        : runStatus === "done"
          ? "Готово"
          : runStatus === "failed"
            ? "Ошибка"
            : "Ожидание";

  const canSend = Boolean(queryText.trim()) && Boolean(selectedProject);

  const appendMessage = useCallback((message: ChatMessage) => {
    setMessages((prev) => [...prev, message].slice(-80));
  }, []);

  const setChatForRun = useCallback((nextRun: Run) => {
    setMessages([
      {
        id: nowId("msg"),
        role: "user",
        content: nextRun.query_text,
        ts: nextRun.created_at ? Date.parse(nextRun.created_at) : Date.now()
      }
    ]);
  }, []);

  const resetEventBuffer = useCallback(() => {
    eventsRef.current = [];
    lastSeqRef.current = 0;
    setEvents([]);
  }, []);

  const pushEvents = useCallback((incoming: EventItem[] | null | undefined) => {
    if (!incoming?.length) return;
    const result = mergeEvents(eventsRef.current, incoming, EVENT_BUFFER_LIMIT);
    eventsRef.current = result.events;
    lastSeqRef.current = result.lastSeq;
    setEvents(result.events);
  }, []);

  const upsertRun = useCallback((nextRun: Run) => {
    setRuns((prev) => {
      const idx = prev.findIndex((item) => item.id === nextRun.id);
      if (idx === -1) {
        return [nextRun, ...prev].slice(0, RUNS_LIMIT);
      }
      const copy = [...prev];
      copy[idx] = nextRun;
      return copy;
    });
  }, []);

  const refreshSnapshot = useCallback(
    async (runId: string) => {
      const snapshot = await getSnapshot(runId);
      setRun(snapshot.run);
      setPlan(snapshot.plan || []);
      setApprovals(snapshot.approvals || []);
      setTasks(snapshot.tasks || []);
      setMetrics(snapshot.metrics || null);
      pushEvents(snapshot.last_events || []);
      if (snapshot.run) upsertRun(snapshot.run);
      return snapshot;
    },
    [pushEvents, upsertRun]
  );

  const refreshSnapshotSafe = useCallback(
    async (runId: string) => {
      if (refreshInFlight.current) {
        refreshQueued.current = true;
        return;
      }
      refreshInFlight.current = true;
      try {
        await refreshSnapshot(runId);
      } finally {
        refreshInFlight.current = false;
        if (refreshQueued.current) {
          refreshQueued.current = false;
          void refreshSnapshotSafe(runId);
        }
      }
    },
    [refreshSnapshot]
  );

  const queueSnapshotRefresh = useCallback(
    (runId: string, delay = 600) => {
      if (refreshTimerRef.current) return;
      refreshTimerRef.current = window.setTimeout(() => {
        refreshTimerRef.current = null;
        void refreshSnapshotSafe(runId);
      }, delay);
    },
    [refreshSnapshotSafe]
  );

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (runId: string) => {
      if (pollTimerRef.current) return;
      setStreamState("polling");
      pollTimerRef.current = window.setInterval(() => {
        void refreshSnapshotSafe(runId);
      }, POLL_INTERVAL_MS);
    },
    [refreshSnapshotSafe]
  );

  const scheduleReconnect = useCallback(
    (runId: string) => {
      if (reconnectTimerRef.current) return;
      const attempt = reconnectAttemptRef.current + 1;
      reconnectAttemptRef.current = attempt;
      const base = Math.min(20000, 800 * Math.pow(2, attempt));
      const jitter = Math.round(base * (0.25 * Math.random()));
      const delay = base + jitter;
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        void openEventStream(runId);
      }, delay);
    },
    []
  );

  const cleanupEventStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    stopPolling();
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, [stopPolling]);

  const handleEvent = useCallback(
    async (type: string, evt: MessageEvent) => {
      try {
        const event = JSON.parse(evt.data) as EventItem;
        pushEvents([event]);
        const targetRun = event.run_id || run?.id;
        if (targetRun) {
          const delay =
            type === "run_done" || type === "run_failed" || type === "run_canceled"
              ? 0
              : type === "approval_requested" || type === "approval_resolved"
                ? 0
                : type === "task_progress"
                  ? 1200
                  : 700;
          queueSnapshotRefresh(targetRun, delay);
        }
        if (type === "run_done" || type === "run_failed" || type === "run_canceled") {
          appendMessage({
            id: nowId("system"),
            role: "system",
            content: statusLabel(type.replace("run_", "")),
            tone: type === "run_failed" ? "error" : "info",
            ts: event.ts
          });
        }
      } catch {
        setStatusMessage("Не удалось прочитать событие");
      }
    },
    [appendMessage, pushEvents, queueSnapshotRefresh, run?.id]
  );

  const openEventStream = useCallback(
    async (runId: string) => {
      cleanupEventStream();
      stopPolling();
      const token = getSessionToken();
      if (!token) {
        await initAuth();
      }
      const safeToken = getSessionToken();
      const url = new URL(`${apiBase()}/runs/${runId}/events`);
      if (safeToken) {
        url.searchParams.set("token", safeToken);
      }
      if (lastSeqRef.current) {
        url.searchParams.set("last_event_id", String(lastSeqRef.current));
      }
      const es = new EventSource(url.toString());
      es.onopen = () => {
        setStreamState("live");
        reconnectAttemptRef.current = 0;
        stopPolling();
        queueSnapshotRefresh(runId, 0);
      };
      es.onerror = () => {
        setStreamState("reconnecting");
        es.close();
        startPolling(runId);
        scheduleReconnect(runId);
      };
      EVENT_TYPES.forEach((type) => {
        es.addEventListener(type, (evt) => void handleEvent(type, evt as MessageEvent));
      });
      eventSourceRef.current = es;
    },
    [cleanupEventStream, handleEvent, queueSnapshotRefresh, scheduleReconnect, startPolling, stopPolling]
  );

  const refreshRuns = useCallback(async (projectId: string) => {
    const data = await listRuns(projectId, RUNS_LIMIT);
    setRuns(data);
    return data;
  }, []);

  const selectRun = useCallback(
    async (runId: string) => {
      if (!runId) return;
      if (run?.id === runId) return;
      resetEventBuffer();
      setRun(null);
      setPlan([]);
      setTasks([]);
      setMetrics(null);
      setApprovals([]);
      setStatusMessage(null);
      const snapshot = await refreshSnapshot(runId);
      if (snapshot.run) {
        setChatForRun(snapshot.run);
        localStorage.setItem(LAST_RUN_KEY, snapshot.run.id);
      }
      void openEventStream(runId);
    },
    [openEventStream, refreshSnapshot, resetEventBuffer, run?.id, setChatForRun]
  );

  const closeRightPanel = useCallback(() => {
    setRightPanel("closed");
  }, []);

  const handleRunCommand = useCallback(async () => {
    if (!selectedProject || !queryText.trim()) return;
    const query = queryText.trim();
    setQueryText("");
    appendMessage({ id: nowId("msg"), role: "user", content: query, ts: Date.now() });
    let response: RunIntentResponse;
    try {
      response = await createRun(selectedProject.id, { query_text: query, mode });
    } catch (err) {
      setStatusMessage("Не удалось запустить");
      appendMessage({
        id: nowId("system"),
        role: "system",
        content: "Ошибка запуска. Проверь API.",
        tone: "error"
      });
      return;
    }
    if (response.kind === "clarify") {
      const questions = response.questions?.filter(Boolean) || [];
      appendMessage({
        id: nowId("assistant"),
        role: "assistant",
        content: questions.join("\n") || "Нужны уточнения."
      });
      return;
    }
    if (response.kind === "chat") {
      appendMessage({
        id: nowId("assistant"),
        role: "assistant",
        content: response.chat_response || "Ответ готов."
      });
      return;
    }
    if (response.kind === "act" && response.run) {
      resetEventBuffer();
      setRun(response.run);
      setChatForRun(response.run);
      localStorage.setItem(LAST_RUN_KEY, response.run.id);
      setPlan([]);
      setTasks([]);
      setMetrics(null);
      setApprovals([]);
      setStatusMessage(null);
      appendMessage({
        id: nowId("system"),
        role: "system",
        content: "Запускаю выполнение…",
        tone: "info"
      });
      void openEventStream(response.run.id);
      try {
        await createPlan(response.run.id);
        await refreshSnapshot(response.run.id);
        await startRun(response.run.id);
        await refreshRuns(response.run.project_id);
      } catch {
        setStatusMessage("Не удалось запустить run");
      }
      return;
    }
    setStatusMessage("Не удалось определить режим запуска.");
  }, [appendMessage, mode, openEventStream, queryText, refreshRuns, refreshSnapshot, resetEventBuffer, selectedProject, setChatForRun]);

  const handleCancelRun = useCallback(async () => {
    if (!run) return;
    try {
      await cancelRun(run.id);
      await refreshSnapshot(run.id);
    } catch {
      setStatusMessage("Не удалось остановить");
    }
  }, [refreshSnapshot, run]);

  const handleApprove = useCallback(
    async (approvalId: string) => {
      await approve(approvalId);
      if (run) await refreshSnapshot(run.id);
    },
    [refreshSnapshot, run]
  );

  const handleReject = useCallback(
    async (approvalId: string) => {
      await reject(approvalId);
      if (run) await refreshSnapshot(run.id);
    },
    [refreshSnapshot, run]
  );

  const refreshMemoryList = useCallback(
    async (queryOverride?: string) => {
      const q = queryOverride ?? memoryQuery;
      try {
        setMemoryLoading(true);
        setMemoryError(null);
        const items = await listUserMemory(q);
        setMemoryItems(items);
      } catch {
        setMemoryError("Не удалось загрузить память");
      } finally {
        setMemoryLoading(false);
      }
    },
    [memoryQuery]
  );

  const handleDeleteMemory = useCallback(
    async (memoryId: string) => {
      try {
        await deleteUserMemory(memoryId);
        await refreshMemoryList();
      } catch {
        setMemoryError("Не удалось удалить запись");
      }
    },
    [refreshMemoryList]
  );

  const handleTogglePin = useCallback(
    async (memoryId: string, pinned: boolean) => {
      try {
        if (pinned) {
          await unpinUserMemory(memoryId);
        } else {
          await pinUserMemory(memoryId);
        }
        await refreshMemoryList();
      } catch {
        setMemoryError("Не удалось обновить запись");
      }
    },
    [refreshMemoryList]
  );

  const handleSaveSettings = useCallback(async () => {
    if (!selectedProject) {
      setSettingsMessage({ text: "Проект не найден", tone: "error" });
      return;
    }
    try {
      setSavingKey(true);
      if (openaiKey.trim()) {
        await storeOpenAIKeyLocal(openaiKey.trim());
        setKeyStored(true);
        setOpenaiKey("");
      }
      const current = selectedProject.settings || {};
      const llm = (current.llm || {}) as NonNullable<ProjectSettings["llm"]>;
      const nextSettings = {
        ...current,
        llm: {
          ...llm,
          provider: "openai",
          base_url: llm.base_url || "https://api.openai.com/v1",
          model: modelName.trim() || llm.model || "gpt-4.1"
        }
      };
      const updated = await updateProject(selectedProject.id, { settings: nextSettings });
      setProjects((prev) => prev.map((proj) => (proj.id === updated.id ? updated : proj)));
      setSettingsMessage({
        text: openaiKey.trim() ? "Ключ и модель сохранены" : "Модель сохранена",
        tone: "success"
      });
    } catch {
      setSettingsMessage({ text: "Не удалось сохранить", tone: "error" });
    } finally {
      setSavingKey(false);
    }
  }, [modelName, openaiKey, selectedProject]);

  useEffect(() => {
    const setup = async () => {
      try {
        await initAuth();
        const data = await listProjects();
        if (!data.length) {
          const created = await createProject({ name: "Основной", tags: ["default"], settings: {} });
          setProjects([created]);
          setSelectedProjectId(created.id);
          localStorage.setItem(LAST_PROJECT_KEY, created.id);
          return;
        }
        setProjects(data);
        const stored = localStorage.getItem(LAST_PROJECT_KEY);
        const next = data.find((project) => project.id === stored) || data[0];
        setSelectedProjectId(next.id);
      } catch {
        setStatusMessage("Не удалось инициализировать API");
      }
    };
    void setup();
  }, []);

  useEffect(() => {
    if (!selectedProject) return;
    localStorage.setItem(LAST_PROJECT_KEY, selectedProject.id);
    const llm = selectedProject.settings?.llm || {};
    setModelName(llm.model || "gpt-4.1");
    refreshRuns(selectedProject.id)
      .then((list) => {
        const storedRun = localStorage.getItem(LAST_RUN_KEY);
        const nextRun = list.find((item) => item.id === storedRun) || list[0] || null;
        if (nextRun) {
          void selectRun(nextRun.id);
        } else {
          setRun(null);
          setPlan([]);
          setTasks([]);
          setMetrics(null);
          setApprovals([]);
          setMessages([]);
          resetEventBuffer();
        }
      })
      .catch(() => setStatusMessage("Не удалось загрузить runs"));
  }, [refreshRuns, resetEventBuffer, selectRun, selectedProject]);

  useEffect(() => {
    localStorage.setItem(RUN_MODE_KEY, mode);
  }, [mode]);

  useEffect(() => {
    localStorage.setItem(OVERLAY_MODE_KEY, overlayMode);
  }, [overlayMode]);

  useEffect(() => {
    const handler = (event: StorageEvent) => {
      if (event.key === OVERLAY_MODE_KEY && event.newValue) {
        const next = event.newValue === "pinned" || event.newValue === "off" ? event.newValue : "auto";
        setOverlayMode(next);
      }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  useEffect(() => {
    const applyOverlay = async () => {
      try {
        if (overlayMode === "off") {
          await invoke("overlay_hide");
          return;
        }
        if (overlayMode === "pinned") {
          await invoke("overlay_show");
          return;
        }
        if (overlayActive) {
          await invoke("overlay_show");
        } else {
          await invoke("overlay_hide");
        }
      } catch {
        // overlay window may be unavailable in dev
      }
    };
    void applyOverlay();
  }, [overlayActive, overlayMode]);

  useEffect(() => {
    if (!statusMessage) return;
    const timer = window.setTimeout(() => setStatusMessage(null), 5200);
    return () => window.clearTimeout(timer);
  }, [statusMessage]);

  useEffect(() => {
    if (!settingsMessage) return;
    const timer = window.setTimeout(() => setSettingsMessage(null), 5200);
    return () => window.clearTimeout(timer);
  }, [settingsMessage]);

  useEffect(() => {
    checkPermissions()
      .then(setPermissions)
      .catch(() => setPermissions(null));
  }, []);

  useEffect(() => {
    if (rightPanel !== "settings") return;
    const check = async () => {
      const ok = await checkApiStatus();
      setApiAvailable(ok);
      try {
        const res = await getLocalOpenAIStatus();
        setKeyStored(res.stored);
      } catch {
        setKeyStored(false);
      }
    };
    void check();
  }, [rightPanel]);

  useEffect(() => {
    if (rightPanel !== "memory") return;
    void refreshMemoryList();
  }, [rightPanel, refreshMemoryList]);

  useEffect(() => {
    const handleKeys = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        if (canSend) {
          void handleRunCommand();
        }
      }
      if (event.key === "Escape") {
        if (rightPanel !== "closed") {
          closeRightPanel();
        }
      }
    };
    window.addEventListener("keydown", handleKeys);
    return () => window.removeEventListener("keydown", handleKeys);
  }, [canSend, closeRightPanel, handleRunCommand, rightPanel]);

  useEffect(() => {
    const setup = async () => {
      const unlistenStop = await listen("autopilot_stop_hotkey", async () => {
        await handleCancelRun();
      });
      return () => {
        unlistenStop();
      };
    };
    void setup();
  }, [handleCancelRun]);

  useEffect(() => {
    const setup = async () => {
      const unlistenInspector = await listen("open_inspector_tab", (event) => {
        const payload = event.payload as { tab?: string } | null;
        setRightPanel("inspector");
        if (payload?.tab === "approvals" || payload?.tab === "events" || payload?.tab === "metrics" || payload?.tab === "steps") {
          setInspectorTab(payload.tab);
        }
      });
      return () => {
        unlistenInspector();
      };
    };
    void setup();
  }, []);

  useEffect(() => {
    if (!run) return;
    return () => cleanupEventStream();
  }, [cleanupEventStream, run]);

  const chatPlaceholder = selectedProject
    ? "Что нужно сделать?"
    : "Создаю проект...";

  const displayRuns = useMemo(() => {
    const query = runSearch.trim().toLowerCase();
    const filtered = query
      ? runs.filter((item) => item.query_text.toLowerCase().includes(query))
      : runs;
    return filtered.slice(0, RUNS_LIMIT);
  }, [runSearch, runs]);

  return (
    <div className="window-frame">
      <div className="titlebar">
        <div className="titlebar-left">Astra</div>
        <div className="window-controls">
          <button className="window-btn close" onClick={() => appWindow.close()} aria-label="Close window" />
          <button className="window-btn minimize" onClick={() => appWindow.minimize()} aria-label="Minimize window" />
          <button className="window-btn maximize" onClick={() => appWindow.toggleMaximize()} aria-label="Maximize window" />
        </div>
      </div>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="sidebar-header">
            <div>
              <div className="brand">Astra</div>
              <div className="brand-sub">{selectedProject?.name || "Проект"}</div>
          </div>
          <div className="badge">v1</div>
        </div>

        <div className="sidebar-section">
          <div className="section-title">Runs</div>
          <div className="sidebar-actions">
            <input
              className="input"
              placeholder="Поиск…"
              value={runSearch}
              onChange={(event) => setRunSearch(event.target.value)}
            />
            <button className="btn ghost small" onClick={() => selectedProject && refreshRuns(selectedProject.id)}>
              Обновить
            </button>
          </div>
          <div className="run-list">
            {displayRuns.length === 0 ? <div className="empty">Пока нет запусков</div> : null}
            {displayRuns.map((item) => {
              const isActive = run?.id === item.id;
              return (
                <button
                  key={item.id}
                  className={`run-item ${isActive ? "active" : ""}`}
                  onClick={() => void selectRun(item.id)}
                >
                  <div className="run-item-title">{shortText(item.query_text || "Без названия", 48)}</div>
                  <div className="run-item-meta">
                    <span className={`pill ${statusTone(item.status)}`}>{statusLabel(item.status)}</span>
                    <span className="muted">{item.created_at ? item.created_at.slice(11, 16) : ""}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="sidebar-footer">
          <button className="btn ghost" onClick={() => setRightPanel("memory")}>Memory</button>
          <button className="btn ghost" onClick={() => setRightPanel("settings")}>Settings</button>
        </div>
        </aside>

        <main className="main">
        <header className="main-header">
          <div className="status-stack">
            <div className="status-row">
              <span className={`pill ${statusToneValue}`}>{runStatusLabel}</span>
              <span className="status-text">{agentStatus}</span>
              {providerStats.last ? (
                <span className="status-chip">
                  {providerStats.last === "local" ? "Local" : providerStats.last === "cloud" ? "Cloud" : providerStats.last}
                </span>
              ) : null}
              <span className={`status-chip ${streamState === "live" ? "ok" : "muted"}`}>
                {streamState === "live" ? "SSE live" : streamState === "polling" ? "Polling" : "Offline"}
              </span>
            </div>
            <div className="status-sub">
              {run ? shortText(run.query_text, 90) : "Готов к запуску"}
            </div>
          </div>
          <div className="header-actions">
            <button
              className="btn ghost small"
              onClick={() => setRightPanel(rightPanel === "inspector" ? "closed" : "inspector")}
            >
              Inspector
            </button>
            {run && run.status === "running" ? (
              <button className="btn danger small" onClick={() => void handleCancelRun()}>
                Stop
              </button>
            ) : null}
          </div>
        </header>

        {statusMessage ? <div className="banner">{statusMessage}</div> : null}

        {visibleApproval ? (
          <div className="approval-banner">
            <div>
              <div className="approval-title">Нужно подтверждение</div>
              <div className="approval-sub">{visibleApproval.title || "Опасное действие"}</div>
            </div>
            <div className="approval-actions">
              <button className="btn ghost" onClick={() => void handleReject(visibleApproval.id)}>
                Reject
              </button>
              <button className="btn primary" onClick={() => void handleApprove(visibleApproval.id)}>
                Approve
              </button>
            </div>
          </div>
        ) : null}

        <section className="chat-thread">
          {messages.length === 0 ? <div className="empty">Сообщения появятся здесь</div> : null}
          {messages.map((message) => (
            <div key={message.id} className={`message ${message.role} ${message.tone || ""}`}>
              <div className="message-role">
                {message.role === "user" ? "You" : message.role === "assistant" ? "Astra" : "System"}
              </div>
              <div className="message-content">{message.content}</div>
              {message.ts ? <div className="message-time">{formatTime(message.ts)}</div> : null}
            </div>
          ))}
        </section>

        <footer className="chat-input">
          <div className="input-row">
            <textarea
              value={queryText}
              onChange={(event) => setQueryText(event.target.value)}
              placeholder={chatPlaceholder}
              rows={3}
            />
            <div className="input-actions">
              <select value={mode} onChange={(event) => setMode(event.target.value)}>
                {MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button className="btn primary" disabled={!canSend} onClick={() => void handleRunCommand()}>
                Send
              </button>
            </div>
          </div>
          <div className="input-hint">Cmd/Ctrl + Enter — отправить</div>
        </footer>
        </main>

        {rightPanel !== "closed" ? (
          <aside className="right-panel">
          {rightPanel === "memory" ? (
            <MemoryPanel
              items={memoryItems}
              query={memoryQuery}
              loading={memoryLoading}
              error={memoryError}
              onQueryChange={setMemoryQuery}
              onRefresh={() => void refreshMemoryList()}
              onDelete={(id) => void handleDeleteMemory(id)}
              onTogglePin={(id, pinned) => void handleTogglePin(id, pinned)}
              onClose={closeRightPanel}
            />
              ) : rightPanel === "settings" ? (
            <SettingsPanel
              modelName={modelName}
              onModelChange={setModelName}
              openaiKey={openaiKey}
              onOpenaiKeyChange={setOpenaiKey}
              keyStored={keyStored}
              apiAvailable={apiAvailable}
              permissions={permissions}
              mode={mode}
              modeOptions={MODE_OPTIONS}
              onModeChange={setMode}
              animatedBg={false}
              onAnimatedBgChange={() => undefined}
              onSave={() => void handleSaveSettings()}
              saving={savingKey}
              message={settingsMessage}
              onClose={closeRightPanel}
              onRefreshPermissions={() =>
                checkPermissions()
                  .then(setPermissions)
                  .catch(() => setPermissions(null))
              }
            />
          ) : (
            <div className="inspector">
              <div className="inspector-header">
                <div>
                  <div className="inspector-title">Inspector</div>
                  <div className="inspector-sub">Run {run?.id ? shortText(run.id, 18) : "—"}</div>
                </div>
                <button className="btn ghost small" onClick={closeRightPanel}>
                  ✕
                </button>
              </div>

              <div className="tab-list">
                {(["steps", "events", "approvals", "metrics"] as InspectorTab[]).map((tab) => (
                  <button
                    key={tab}
                    className={`tab ${inspectorTab === tab ? "active" : ""}`}
                    onClick={() => setInspectorTab(tab)}
                  >
                    {tab === "steps"
                      ? "Steps"
                      : tab === "events"
                        ? "Events"
                        : tab === "approvals"
                          ? "Approvals"
                          : "Metrics"}
                  </button>
                ))}
              </div>

              <div className="panel-body">
                {inspectorTab === "steps" ? (
                  <div className="panel-section">
                    {plan.length === 0 ? <div className="empty">Шаги появятся после планирования</div> : null}
                    <div className="step-list">
                      {plan.map((step, index) => {
                        const stepIndex = typeof step.step_index === "number" ? step.step_index + 1 : index + 1;
                        const isActive = activeStepId === step.id;
                        return (
                          <div key={step.id} className={`step-item ${isActive ? "active" : ""}`}>
                            <div className="step-title">
                              <span className="step-index">{stepIndex}.</span>
                              <span>{step.title}</span>
                            </div>
                            <div className="step-meta">
                              {step.kind ? <span className="tag">{step.kind}</span> : null}
                              {step.requires_approval ? <span className="tag warn">approval</span> : null}
                              <span className={`pill ${statusTone(step.status)}`}>{statusLabel(step.status)}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {inspectorTab === "events" ? (
                  <div className="panel-section">
                    <div className="panel-controls">
                      <input
                        className="input"
                        placeholder="Фильтр событий"
                        value={eventSearch}
                        onChange={(event) => setEventSearch(event.target.value)}
                      />
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={errorsOnly}
                          onChange={(event) => setErrorsOnly(event.target.checked)}
                        />
                        Только ошибки
                      </label>
                    </div>
                    <div className="event-list">
                      {visibleEvents.length === 0 ? <div className="empty">Событий пока нет</div> : null}
                      {visibleEvents.map((event) => (
                        <div key={`${event.seq ?? event.id}`} className="event-item">
                          <div className="event-head">
                            <span className="event-type">{event.type}</span>
                            <span className="muted">{event.ts ? formatTime(event.ts) : ""}</span>
                          </div>
                          {event.message ? <div className="event-msg">{event.message}</div> : null}
                          {event.payload && Object.keys(event.payload).length > 0 ? (
                            <details>
                              <summary>payload</summary>
                              <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                            </details>
                          ) : null}
                        </div>
                      ))}
                    </div>
                    {filteredEvents.length > eventLimit ? (
                      <button className="btn ghost small" onClick={() => setEventLimit((prev) => prev + EVENT_PAGE_SIZE)}>
                        Load more
                      </button>
                    ) : null}
                  </div>
                ) : null}

                {inspectorTab === "approvals" ? (
                  <div className="panel-section">
                    {approvals.length === 0 ? <div className="empty">Approval пока нет</div> : null}
                    <div className="approval-list">
                      {approvals.map((approval) => {
                        const preview = isRecord(approval.preview) ? approval.preview : null;
                        const summary =
                          (preview && typeof preview.summary === "string" ? preview.summary : null) ||
                          approval.title ||
                          "Нужно подтверждение";
                        const risk = preview && typeof preview.risk === "string" ? preview.risk : null;
                        const details = preview && isRecord(preview.details) ? preview.details : null;
                        return (
                          <div key={approval.id} className={`approval-card ${approval.status}`}>
                            <div className="approval-head">
                              <span className="approval-status">{approval.status}</span>
                              <span className="muted">{approval.approval_type || ""}</span>
                            </div>
                            <div className="approval-summary">{summary}</div>
                            {risk ? <div className="approval-risk">{risk}</div> : null}
                            {details ? (
                              <div className="approval-details">
                                {Object.entries(details).map(([key, value]) => (
                                  <div key={key}>
                                    <span className="muted">{key}: </span>
                                    <span>{String(value)}</span>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                            {approval.status === "pending" ? (
                              <div className="approval-actions">
                                <button className="btn ghost" onClick={() => void handleReject(approval.id)}>
                                  Reject
                                </button>
                                <button className="btn primary" onClick={() => void handleApprove(approval.id)}>
                                  Approve
                                </button>
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {inspectorTab === "metrics" ? (
                  <div className="panel-section">
                    <div className="metrics-grid">
                      <div className="metric-card">
                        <div className="metric-label">Steps</div>
                        <div className="metric-value">{stepStats.done} / {stepStats.total}</div>
                      </div>
                      <div className="metric-card">
                        <div className="metric-label">Errors</div>
                        <div className="metric-value">{errorCount}</div>
                      </div>
                      <div className="metric-card">
                        <div className="metric-label">Pauses</div>
                        <div className="metric-value">{pauseCount}</div>
                      </div>
                      <div className="metric-card">
                        <div className="metric-label">LLM Local</div>
                        <div className="metric-value">{providerStats.local}</div>
                      </div>
                      <div className="metric-card">
                        <div className="metric-label">LLM Cloud</div>
                        <div className="metric-value">{providerStats.cloud}</div>
                      </div>
                      <div className="metric-card">
                        <div className="metric-label">Active</div>
                        <div className="metric-value">{run ? runStatusLabel : "—"}</div>
                      </div>
                    </div>
                    {metrics?.coverage ? (
                      <div className="metric-note">
                        Coverage: {metrics.coverage.done}/{metrics.coverage.total}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          )}
          </aside>
        ) : null}
      </div>
    </div>
  );
}
