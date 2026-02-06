import React, { useEffect, useMemo, useState } from "react";
import {
  apiBase,
  listProjects,
  createProject,
  updateProject,
  createRun,
  createPlan,
  startRun,
  cancelRun,
  pauseRun,
  resumeRun,
  getSnapshot,
  initAuth,
  checkApiStatus,
  getSessionToken,
  checkPermissions,
  storeOpenAIKeyLocal,
  getLocalOpenAIStatus,
  approve,
  reject,
  retryStep,
  downloadArtifact,
  downloadSnapshot
} from "./api";
import { ru } from "./i18n/ru";
import { listen } from "@tauri-apps/api/event";
import { appWindow, LogicalPosition, LogicalSize } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/tauri";

const t = ru;

// EN kept: типы событий — публичный контракт API
const EVENT_TYPES = [
  "run_created",
  "plan_created",
  "run_started",
  "run_done",
  "run_failed",
  "run_canceled",
  "run_paused",
  "run_resumed",
  "task_queued",
  "task_started",
  "task_progress",
  "task_failed",
  "task_retried",
  "task_done",
  "source_found",
  "source_fetched",
  "fact_extracted",
  "artifact_created",
  "conflict_detected",
  "verification_done",
  "approval_requested",
  "approval_approved",
  "approval_rejected",
  "autopilot_state",
  "autopilot_action"
];

// EN kept: значения режимов — публичный контракт API
const MODE_OPTIONS = [
  { value: "plan_only", label: t.modes.plan_only },
  { value: "research", label: t.modes.research },
  { value: "execute_confirm", label: t.modes.execute_confirm },
  { value: "autopilot_safe", label: t.modes.autopilot_safe }
];

const HUD_WINDOW_MODE = "astra_window_mode";
const HUD_WINDOW_SIZE = "astra_window_size";
const HUD_OVERLAY_SIZE = "astra_overlay_size";
const HUD_OVERLAY_POS = "astra_overlay_pos";
const SETTINGS_VIEW = "settings";

function label(map: Record<string, string>, key: string, fallback: string) {
  return map[key] || fallback;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function formatFreshness(metrics: any) {
  const freshness = metrics?.freshness;
  if (!freshness || !freshness.max) return t.labels.freshnessEmpty;
  try {
    const date = new Date(freshness.max);
    return date.toLocaleString("ru-RU");
  } catch {
    return freshness.max;
  }
}

function formatCoverage(metrics: any) {
  const coverage = metrics?.coverage;
  if (!coverage) return "0/0";
  return `${coverage.done}/${coverage.total}`;
}

function AstraHud() {
  const isSettingsView = new URLSearchParams(window.location.search).get("view") === SETTINGS_VIEW;
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<any | null>(null);
  const [run, setRun] = useState<any | null>(null);
  const [plan, setPlan] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any | null>(null);
  const [autopilotState, setAutopilotState] = useState<any | null>(null);
  const [recentActions, setRecentActions] = useState<any[]>([]);
  const [queryText, setQueryText] = useState("");
  const [mode, setMode] = useState("execute_confirm");
  const [status, setStatus] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [permissions, setPermissions] = useState<any | null>(null);
  const [openaiKey, setOpenaiKeyValue] = useState("");
  const [apiKeyReady, setApiKeyReady] = useState(false);
  const [keyStored, setKeyStored] = useState(false);
  const [savingVault, setSavingVault] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState<{ text: string; tone: "success" | "error" | "info" } | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(null);
  const [modelName, setModelName] = useState("gpt-4.1-mini");
  const [loopDelayMs, setLoopDelayMs] = useState(650);
  const [maxActions, setMaxActions] = useState(6);
  const [maxCycles, setMaxCycles] = useState(30);
  const [windowMode, setWindowMode] = useState<"window" | "overlay">("window");
  const settingsSizeRef = React.useRef<{ width: number; height: number } | null>(null);
  const settingsPrevModeRef = React.useRef<"window" | "overlay" | null>(null);

  const eventSourceRef = React.useRef<EventSource | null>(null);
  const refreshLock = React.useRef(false);

  useEffect(() => {
    if (isSettingsView) {
      setSettingsOpen(true);
    }
    initAuth()
      .then(async () => {
        await loadProjects();
        const last = localStorage.getItem("astra_last_run_id");
        if (last) {
          await refreshSnapshot(last);
          openEventStream(last);
        }
      })
      .catch((err) => setStatus(err.message || t.errors.authInit));
  }, []);

  useEffect(() => {
    const checkApi = async () => {
      const ok = await checkApiStatus();
      setApiAvailable(ok);
    };
    if (settingsOpen || isSettingsView) {
      checkApi();
    }
  }, [settingsOpen, isSettingsView]);

  useEffect(() => {
    const checkLocalKey = async () => {
      try {
        const res = await getLocalOpenAIStatus();
        setKeyStored(res.stored);
      } catch {
        setKeyStored(false);
      }
    };
    if (settingsOpen || isSettingsView) {
      checkLocalKey();
    }
  }, [settingsOpen, isSettingsView]);

  useEffect(() => {
    if (!settingsMessage) return;
    const timer = setTimeout(() => setSettingsMessage(null), 5000);
    return () => clearTimeout(timer);
  }, [settingsMessage]);

  useEffect(() => {
    if (isSettingsView) return;
    const resizeForSettings = async () => {
      if (settingsOpen) {
        const size = await appWindow.innerSize();
        settingsSizeRef.current = { width: size.width, height: size.height };
        const targetWidth = Math.max(size.width, 980);
        const targetHeight = Math.max(size.height, 700);
        if (windowMode === "overlay") {
          settingsPrevModeRef.current = "overlay";
          await applyWindowMode(false, { width: targetWidth, height: targetHeight });
          await sleep(120);
          await appWindow.setSize(new LogicalSize(targetWidth, targetHeight));
        } else {
          await appWindow.setMinSize(new LogicalSize(820, 520));
          await sleep(80);
          await appWindow.setSize(new LogicalSize(targetWidth, targetHeight));
          await sleep(80);
          await appWindow.setSize(new LogicalSize(targetWidth, targetHeight));
        }
      } else if (settingsSizeRef.current) {
        const prev = settingsSizeRef.current;
        settingsSizeRef.current = null;
        if (settingsPrevModeRef.current === "overlay") {
          settingsPrevModeRef.current = null;
          await applyOverlayMode(false);
          await sleep(80);
          await appWindow.setSize(new LogicalSize(prev.width, prev.height));
        } else {
          await appWindow.setMinSize(windowMode === "overlay" ? new LogicalSize(420, 200) : new LogicalSize(640, 360));
          await sleep(80);
          await appWindow.setSize(new LogicalSize(prev.width, prev.height));
        }
      }
    };
    resizeForSettings();
  }, [settingsOpen, windowMode, isSettingsView]);

  useEffect(() => {
    if (!selectedProject && projects.length > 0) {
      setSelectedProject(projects[0]);
    }
  }, [projects, selectedProject]);

  useEffect(() => {
    if (!selectedProject) return;
    const settings = selectedProject.settings || {};
    const llm = settings.llm || {};
    const autopilot = settings.autopilot || {};
    setModelName(llm.model || "gpt-4.1-mini");
    setLoopDelayMs(Number(autopilot.loop_delay_ms ?? 650));
    setMaxActions(Number(autopilot.max_actions ?? 6));
    setMaxCycles(Number(autopilot.max_cycles ?? 30));
  }, [selectedProject]);

  useEffect(() => {
    checkPermissions()
      .then(setPermissions)
      .catch(() => setPermissions(null));
  }, []);

  useEffect(() => {
    if (isSettingsView) return;
    const unlisten = listen("autopilot_stop_hotkey", async () => {
      if (run) {
        await cancelRun(run.id);
        await refreshSnapshot(run.id);
      }
    });
    const unlistenToggle = listen("toggle_hud_mode", async () => {
      await toggleOverlayMode();
    });
    return () => {
      unlisten.then((fn) => fn());
      unlistenToggle.then((fn) => fn());
    };
  }, [run, windowMode, isSettingsView]);

  useEffect(() => {
    if (isSettingsView) return;
    const saved = (localStorage.getItem(HUD_WINDOW_MODE) as "window" | "overlay") || "window";
    if (saved === "overlay") {
      applyOverlayMode();
    } else {
      applyWindowMode();
    }
    const unlistenResize = appWindow.onResized(async () => {
      const size = await appWindow.innerSize();
      if (windowMode === "overlay") {
        localStorage.setItem(HUD_OVERLAY_SIZE, JSON.stringify({ width: size.width, height: size.height }));
      } else {
        localStorage.setItem(HUD_WINDOW_SIZE, JSON.stringify({ width: size.width, height: size.height }));
      }
    });
    const unlistenMove = appWindow.onMoved(async () => {
      if (windowMode !== "overlay") return;
      const pos = await appWindow.outerPosition();
      localStorage.setItem(HUD_OVERLAY_POS, JSON.stringify({ x: pos.x, y: pos.y }));
    });
    return () => {
      unlistenResize.then((fn) => fn());
      unlistenMove.then((fn) => fn());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSettingsView]);

  async function applyWindowMode(persist = true, overrideSize?: { width: number; height: number }) {
    const sizeRaw = localStorage.getItem(HUD_WINDOW_SIZE);
    const size = overrideSize || (sizeRaw ? JSON.parse(sizeRaw) : { width: 900, height: 520 });
    await appWindow.setDecorations(true);
    await appWindow.setAlwaysOnTop(false);
    await appWindow.setFullscreen(false);
    await appWindow.setResizable(true);
    await appWindow.setMinSize(new LogicalSize(640, 360));
    await sleep(80);
    await appWindow.setSize(new LogicalSize(size.width, size.height));
    await sleep(80);
    await appWindow.setSize(new LogicalSize(size.width, size.height));
    if (persist) {
      localStorage.setItem(HUD_WINDOW_MODE, "window");
    }
    setWindowMode("window");
  }

  async function applyOverlayMode(persist = true) {
    const sizeRaw = localStorage.getItem(HUD_OVERLAY_SIZE);
    const posRaw = localStorage.getItem(HUD_OVERLAY_POS);
    const size = sizeRaw ? JSON.parse(sizeRaw) : { width: 520, height: 220 };
    const pos = posRaw ? JSON.parse(posRaw) : null;
    await appWindow.setDecorations(false);
    await appWindow.setAlwaysOnTop(true);
    await appWindow.setFullscreen(false);
    await appWindow.setResizable(true);
    await appWindow.setMinSize(new LogicalSize(420, 200));
    await sleep(80);
    await appWindow.setSize(new LogicalSize(size.width, size.height));
    await sleep(80);
    await appWindow.setSize(new LogicalSize(size.width, size.height));
    if (pos) {
      await appWindow.setPosition(new LogicalPosition(pos.x, pos.y));
    }
    if (persist) {
      localStorage.setItem(HUD_WINDOW_MODE, "overlay");
    }
    setWindowMode("overlay");
  }

  async function toggleOverlayMode() {
    if (windowMode === "overlay") {
      await applyWindowMode();
    } else {
      await applyOverlayMode();
    }
  }

  async function openSettingsWindow() {
    try {
      await invoke("open_settings_window");
    } catch (err: any) {
      setStatus(err?.message || "Не удалось открыть окно настроек");
    }
  }

  function closeSettingsWindow() {
    if (isSettingsView) {
      appWindow.close();
      return;
    }
    setSettingsOpen(false);
  }

  async function loadProjects() {
    const data = await listProjects();
    if (data.length === 0) {
      const created = await createProject({ name: "Основной", tags: ["default"], settings: {} });
      setProjects([created]);
      setSelectedProject(created);
      return;
    }
    setProjects(data);
  }

  async function applySettingsToProject(projectId: string) {
    const settings = {
      llm: {
        provider: "openai",
        base_url: "https://api.openai.com/v1",
        model: modelName.trim() || "gpt-4.1-mini",
      },
      autopilot: {
        loop_delay_ms: Math.max(200, Number(loopDelayMs) || 650),
        max_actions: Math.max(1, Number(maxActions) || 6),
        max_cycles: Math.max(1, Number(maxCycles) || 30),
      }
    };
    await updateProject(projectId, { settings });
  }

  async function ensureApiKey(): Promise<boolean> {
    if (apiKeyReady) return true;
    try {
      const res = await getLocalOpenAIStatus();
      if (!res.stored) {
        setStatus("API-ключ не найден. Откройте настройки и сохраните ключ.");
        return false;
      }
      setApiKeyReady(true);
      return true;
    } catch (err: any) {
      setStatus(err?.message || "Не удалось проверить ключ. Откройте настройки.");
      return false;
    }
  }

  async function handleSaveProvider() {
    if (!openaiKey) {
      setStatus(t.onboarding.keyRequired);
      setSettingsMessage({ text: t.onboarding.keyRequired, tone: "error" });
      return;
    }
    try {
      setSavingVault(true);
      await storeOpenAIKeyLocal(openaiKey);
      setKeyStored(true);
      if (selectedProject) {
        await applySettingsToProject(selectedProject.id);
        setApiKeyReady(true);
        setSettingsMessage({ text: "Ключ сохранён локально и активирован", tone: "success" });
      } else {
        setSettingsMessage({ text: "Ключ сохранён локально. Запустите API для активации.", tone: "info" });
      }
      setOpenaiKeyValue("");
      setStatus("Ключ сохранён локально");
    } catch (err: any) {
      setStatus(err.message || t.onboarding.vaultError);
      setSettingsMessage({ text: err.message || t.onboarding.vaultError, tone: "error" });
    } finally {
      setSavingVault(false);
    }
  }


  async function handleRunCommand() {
    if (!selectedProject || !queryText.trim()) return;
    const ok = await ensureApiKey();
    if (!ok) return;
    const newRun = await createRun(selectedProject.id, { query_text: queryText, mode });
    setRun(newRun);
    localStorage.setItem("astra_last_run_id", newRun.id);
    setEvents([]);
    setPlan([]);
    setTasks([]);
    setApprovals([]);
    setArtifacts([]);
    setMetrics(null);
    await createPlan(newRun.id);
    await refreshSnapshot(newRun.id);
    await startRun(newRun.id);
    openEventStream(newRun.id);
  }

  async function handleCreatePlan() {
    if (!run) return;
    await createPlan(run.id);
    await refreshSnapshot(run.id);
  }

  async function handleStartRun() {
    if (!run) return;
    await startRun(run.id);
    openEventStream(run.id);
  }

  async function handleCancelRun() {
    if (!run) return;
    await cancelRun(run.id);
    await refreshSnapshot(run.id);
  }

  async function handlePauseToggle() {
    if (!run) return;
    if (run.status === "paused") {
      await resumeRun(run.id);
    } else {
      await pauseRun(run.id);
    }
    await refreshSnapshot(run.id);
  }

  async function handleRetryStep(stepId: string) {
    if (!run) return;
    await retryStep(run.id, stepId);
  }

  async function handleExportSnapshot() {
    if (!run) return;
    const blob = await downloadSnapshot(run.id);
    downloadBlob(blob, `снимок_${run.id}.json`);
  }

  async function handleExportReport() {
    if (!run) return;
    const report = artifacts.find((a) => a.type === "report_md");
    if (!report) return;
    const blob = await downloadArtifact(report.id);
    downloadBlob(blob, `отчет_${run.id}.md`);
  }

  async function handleApprove(approvalId: string) {
    await approve(approvalId);
    if (run) await refreshSnapshot(run.id);
  }

  async function handleReject(approvalId: string) {
    await reject(approvalId);
    if (run) await refreshSnapshot(run.id);
  }

  function openEventStream(runId: string) {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    const token = getSessionToken();
    const es = new EventSource(`${apiBase()}/runs/${runId}/events?token=${token}`);
    EVENT_TYPES.forEach((type) => {
      es.addEventListener(type, (evt) => handleEvent(type, evt as MessageEvent));
    });
    es.onerror = () => {
      setStatus(t.errors.eventStream);
    };
    eventSourceRef.current = es;
  }

  async function handleEvent(type: string, evt: MessageEvent) {
    try {
      const payload = JSON.parse(evt.data);
      if (type === "autopilot_state") {
        setAutopilotState(payload);
      }
      if (type === "autopilot_action") {
        setRecentActions((prev) => [payload, ...prev].slice(0, 10));
      }
      setEvents((prev) => [payload, ...prev].slice(0, 200));
      if (!refreshLock.current) {
        refreshLock.current = true;
        await refreshSnapshot(payload.run_id || run?.id);
        refreshLock.current = false;
      }
      if (type === "run_done" || type === "run_failed" || type === "run_canceled") {
        setStatus(label(t.events, type, type));
      }
    } catch (err: any) {
      setStatus(err.message || t.errors.parseEvent);
    }
  }

  async function refreshSnapshot(runId?: string) {
    const id = runId || run?.id;
    if (!id) return;
    const snapshot = await getSnapshot(id);
    setRun(snapshot.run);
    setPlan(snapshot.plan || []);
    setTasks(snapshot.tasks || []);
    setApprovals(snapshot.approvals || []);
    setArtifacts(snapshot.artifacts || []);
    setMetrics(snapshot.metrics || null);
  }

  const pendingApprovals = useMemo(() => approvals.filter((a) => a.status === "pending"), [approvals]);
  const reportArtifact = useMemo(() => artifacts.find((a) => a.type === "report_md"), [artifacts]);
  const keyStatusLabel = apiKeyReady
    ? "Ключ активен"
    : keyStored
      ? "Ключ сохранён в файле"
      : "Ключ не сохранён";

  const runStatus = run?.status || "idle";
  const isActive = ["running", "paused"].includes(runStatus);
  const isDone = ["done", "failed", "canceled"].includes(runStatus);
  const uiMode = isActive ? "active" : isDone ? "done" : "idle";

  const overlayStatus = autopilotState?.status || runStatus || "idle";
  const overlayStatusLabel = ({
    running: "Делает",
    waiting_confirm: "Ждёт подтверждение",
    needs_user: "Нужна помощь",
    done: "Готово",
    failed: "Ошибка",
    paused: "Пауза",
    idle: "Ожидание",
  } as Record<string, string>)[overlayStatus] || label(t.runStatus, overlayStatus, overlayStatus);

  const phaseLabel = (() => {
    const phase = autopilotState?.phase;
    if (phase === "thinking") return "думает";
    if (phase === "acting") return "делает";
    if (overlayStatus === "waiting_confirm") return "ждёт подтверждение";
    if (overlayStatus === "needs_user") return "нужна помощь";
    return "ожидание";
  })();

  const isOverlay = windowMode === "overlay";
  const planLimit = isOverlay ? 5 : 12;
  const actionsLimit = isOverlay ? 4 : 10;
  const eventsLimit = isOverlay ? 2 : 6;

  const latestPlan = plan.slice(0, planLimit);
  const latestActions = (autopilotState?.actions || []).slice(0, actionsLimit);
  const latestEvents = events.slice(0, eventsLimit);

  const tasksByStep = useMemo(() => {
    const map = new Map<string, any[]>();
    tasks.forEach((task) => {
      const list = map.get(task.plan_step_id) || [];
      list.push(task);
      map.set(task.plan_step_id, list);
    });
    return map;
  }, [tasks]);

  const stepStatusLabel = (step: any) => {
    const status = step.status;
    if (status === "running") return "делает";
    if (status === "failed") return "ошибка";
    if (status === "done") return "готово";
    return "думает";
  };

  const activeStep = plan.find((step) => step.status === "running") || plan[0];

  const settingsPanel = (
    <aside className={`hud-settings ${isSettingsView || settingsOpen ? "open" : ""} ${isSettingsView ? "settings-window" : ""}`}>
      <div className="hud-settings-header">
        <div className="hud-settings-title">
          <div className="hud-section-title">Настройки Astra</div>
          <div className="hud-meta">Подключения, разрешения и режим работы</div>
        </div>
        <button className="ghost" onClick={closeSettingsWindow}>Закрыть</button>
      </div>

      {settingsMessage && (
        <div className={`settings-banner ${settingsMessage.tone}`}>
          {settingsMessage.text}
        </div>
      )}

      <section className="settings-card">
        <div className="settings-card-title">Подключение</div>
        <div className="settings-status-row">
          <div className={`status-dot ${apiKeyReady ? "on" : keyStored ? "warm" : "off"}`} />
          <div className="hud-meta">{keyStatusLabel}</div>
          <div className="hud-meta">
            API: {apiAvailable === null ? "проверка…" : apiAvailable ? "подключен" : "не отвечает"}
          </div>
        </div>
        {apiAvailable === false && (
          <div className="hud-meta">Запустите локальный API, чтобы активировать ключ.</div>
        )}
        <label className="hud-field">
          <span>Модель</span>
          <input
            type="text"
            placeholder="gpt-4.1-mini"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
          />
        </label>
        <label className="hud-field">
          <span>API ключ</span>
          <input
            type="password"
            placeholder={t.onboarding.openaiKeyPlaceholder}
            value={openaiKey}
            onChange={(e) => setOpenaiKeyValue(e.target.value)}
          />
        </label>
        <div className="settings-actions">
          <button className="primary" disabled={savingVault || !openaiKey.trim()} onClick={handleSaveProvider}>
            {savingVault ? t.onboarding.saving : "Сохранить локально"}
          </button>
        </div>
        <div className="hud-meta">Файл ключа: config/local.secrets.json</div>
      </section>

      <section className="settings-card">
        <div className="settings-card-title">Разрешения macOS</div>
        <div className="settings-perms">
          <div className="settings-perm">
            <span>Screen Recording</span>
            <span className={permissions?.screen_recording ? "perm-on" : "perm-off"}>
              {permissions?.screen_recording ? "включено" : "не включено"}
            </span>
          </div>
          <div className="settings-perm">
            <span>Accessibility</span>
            <span className={permissions?.accessibility ? "perm-on" : "perm-off"}>
              {permissions?.accessibility ? "включено" : "не включено"}
            </span>
          </div>
        </div>
        <div className="hud-row">
          <button onClick={async () => setPermissions(await checkPermissions())}>{t.onboarding.permissionsCheck}</button>
        </div>
      </section>

      <button className="settings-advanced-toggle" onClick={() => setAdvancedOpen((prev) => !prev)}>
        {advancedOpen ? "Скрыть расширенные настройки" : "Расширенные настройки"}
      </button>

      {advancedOpen && (
        <div className="settings-advanced">
          <section className="settings-card">
            <div className="settings-card-title">Режим работы</div>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              {MODE_OPTIONS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </section>

          <section className="settings-card">
            <div className="settings-card-title">Автопилот</div>
            <label className="hud-field">
              <span>Интервал цикла (мс)</span>
              <input type="number" min={200} max={3000} value={loopDelayMs} onChange={(e) => setLoopDelayMs(Number(e.target.value))} />
            </label>
            <label className="hud-field">
              <span>Действий за цикл</span>
              <input type="number" min={1} max={10} value={maxActions} onChange={(e) => setMaxActions(Number(e.target.value))} />
            </label>
            <label className="hud-field">
              <span>Лимит циклов</span>
              <input type="number" min={1} max={120} value={maxCycles} onChange={(e) => setMaxCycles(Number(e.target.value))} />
            </label>
          </section>

          {projects.length > 0 && (
            <section className="settings-card">
              <div className="settings-card-title">Проект</div>
              <select value={selectedProject?.id || ""} onChange={(e) => setSelectedProject(projects.find((p) => p.id === e.target.value))}>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </section>
          )}
        </div>
      )}
    </aside>
  );

  if (isSettingsView) {
    return (
      <div className="app settings-only">
        <div className="settings-shell">{settingsPanel}</div>
      </div>
    );
  }

  return (
    <div className={`app hud-app mode-${uiMode} mode-${windowMode} ${settingsOpen ? "settings-open" : ""}`}>
      <div className="hud-shell">
        <div className="hud-top-zone" />
        <header className="hud-header">
          <div className="hud-actions">
            <button className="icon-button" title="Настройки" onClick={openSettingsWindow}>
              ⚙︎
            </button>
            <button className="icon-button" title="Переключить режим" onClick={toggleOverlayMode}>
              ⤢
            </button>
            {isActive && (
              <button className="icon-button danger" title="Стоп" onClick={handleCancelRun}>
                ■
              </button>
            )}
          </div>
        </header>

        <div className="hud-content">
          {uiMode === "idle" && (
            <section className="hud-idle">
              <div className="hud-idle-header">
                <div className="hud-logo">A</div>
              </div>
              <div className="hud-greeting">Что нужно сделать?</div>
              <div className="hud-input-row">
                <input
                  className="hud-input"
                  type="text"
                  placeholder={t.hud.placeholder}
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleRunCommand();
                    }
                  }}
                />
                <button
                  className="send-button"
                  title="Запустить"
                  onClick={handleRunCommand}
                  disabled={!selectedProject || !queryText.trim() || isActive}
                >
                  ➤
                </button>
              </div>
              {status && <div className="hud-message">{status}</div>}
            </section>
          )}

          {uiMode !== "idle" && (
            <section className="hud-exec">
              <div className="hud-brand">ASTRA</div>
              <div className="hud-section">
                <div className="hud-section-title">Сейчас</div>
                <div className="hud-value">{autopilotState?.step_summary || activeStep?.title || "—"}</div>
                <div className="hud-meta">Статус: {phaseLabel}</div>
                <div className="hud-meta">Размышление: {autopilotState?.reason || "—"}</div>
                <div className="hud-meta">Цель: {autopilotState?.goal || run?.query_text || "—"}</div>
              </div>

              <div className="hud-section">
                <div className="hud-section-title">Задачи</div>
                <ul className="hud-list scrollable">
                  {latestPlan.map((step) => (
                    <li key={step.id}>
                      <div className="hud-list-title">{step.step_index + 1}. {step.title}</div>
                      <div className={`hud-list-sub status-${step.status}`}>{stepStatusLabel(step)}</div>
                      {!isOverlay && tasksByStep.get(step.id)?.length ? (
                        <ul className="hud-sublist">
                          {tasksByStep.get(step.id)!.slice(0, 3).map((task) => (
                            <li key={task.id}>
                              <div className="hud-list-sub">{label(t.taskStatus, task.status, task.status)}</div>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {step.status === "failed" && (
                        <div className="hud-row">
                          <button onClick={() => handleRetryStep(step.id)}>{t.workspace.retryStep}</button>
                        </div>
                      )}
                    </li>
                  ))}
                  {!latestPlan.length && <li className="muted">{t.empty.plan}</li>}
                </ul>
              </div>

              <div className="hud-section">
                <div className="hud-section-title">Действия</div>
                <div className="hud-actions-row">
                  {latestActions.map((action: any, idx: number) => (
                    <span key={`action-${idx}`} className="hud-chip">{action.type}</span>
                  ))}
                  {!latestActions.length && <span className="hud-chip muted">—</span>}
                </div>
              </div>

              {!isOverlay && (
                <div className="hud-section">
                  <div className="hud-section-title">Журнал</div>
                  <ul className="hud-list scrollable">
                    {latestEvents.map((evt) => (
                      <li key={`${evt.id}-${evt.seq}`}>
                        <div className="hud-list-title">{label(t.events, evt.type, evt.type)}</div>
                        <div className="hud-list-sub">{evt.message}</div>
                      </li>
                    ))}
                    {!latestEvents.length && <li className="muted">{t.empty.events}</li>}
                  </ul>
                </div>
              )}

              {pendingApprovals[0] && (
                <div className="hud-section hud-approval">
                  <div className="hud-section-title">Подтверждение</div>
                  <div className="hud-value">{pendingApprovals[0].title}</div>
                  {pendingApprovals[0].description && <div className="hud-meta">{pendingApprovals[0].description}</div>}
                  <div className="hud-row">
                    <button className="primary" onClick={() => handleApprove(pendingApprovals[0].id)}>{t.workspace.approve}</button>
                    <button className="danger" onClick={() => handleReject(pendingApprovals[0].id)}>{t.workspace.reject}</button>
                  </div>
                </div>
              )}

              {isDone && (
                <div className="hud-section">
                  <div className="hud-section-title">Итог</div>
                  <div className="hud-value">{overlayStatusLabel}</div>
                </div>
              )}
            </section>
          )}

          {uiMode !== "idle" && !isOverlay && (
            <footer className="hud-footer">
              <span className="hud-pill">{t.labels.coverage} {formatCoverage(metrics)}</span>
              <span className="hud-pill">{t.labels.conflicts} {metrics?.conflicts ?? 0}</span>
              <span className="hud-pill">{t.labels.freshness} {formatFreshness(metrics)}</span>
              <span className="hud-pill">{t.labels.approvals} {pendingApprovals.length}</span>
              <button className="ghost" onClick={handleExportSnapshot} disabled={!run}>{t.workspace.exportJson}</button>
              <button className="ghost" onClick={handleExportReport} disabled={!reportArtifact}>{t.workspace.exportMd}</button>
            </footer>
          )}

          {status && uiMode !== "idle" && <div className="hud-toast">{status}</div>}
        </div>
      </div>

      {settingsOpen ? settingsPanel : null}
    </div>
  );
}

export default function App() {
  return <AstraHud />;
}
