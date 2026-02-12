import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/tauri";
import {
  apiBase,
  cancelRun,
  getSessionToken,
  getSnapshot,
  initAuth,
  pauseRun,
  resumeRun
} from "./api";
import type { Approval, EventItem, PlanStep, Run, Task } from "./types";
import { mergeEvents } from "./ui/utils";
import { deriveOverlayStatus } from "./ui/overlay_utils";

const EVENT_TYPES = [
  "approval_requested",
  "approval_resolved",
  "approval_approved",
  "approval_rejected",
  "run_started",
  "run_paused",
  "run_resumed",
  "run_done",
  "run_failed",
  "run_canceled",
  "reminder_due",
  "reminder_sent",
  "reminder_failed",
  "task_started",
  "task_progress",
  "task_failed",
  "task_done",
  "step_execution_started",
  "step_execution_finished",
  "step_paused_for_approval"
];

const EVENT_BUFFER_LIMIT = 120;
const OVERLAY_MODE_KEY = "astra_overlay_mode";
const LAST_RUN_KEY = "astra_last_run_id";

type OverlayMode = "auto" | "pinned" | "off";

type StepSummary = {
  title: string;
  index: number;
  total: number;
  requiresApproval: boolean;
};

function getStoredOverlayMode(): OverlayMode {
  const stored = localStorage.getItem(OVERLAY_MODE_KEY);
  if (stored === "pinned" || stored === "off") return stored;
  return "auto";
}

function getStoredRunId() {
  return localStorage.getItem(LAST_RUN_KEY);
}

function selectActiveStep(plan: PlanStep[], tasks: Task[]): StepSummary | null {
  const total = plan.length;
  if (!total) return null;
  const runningTask = tasks.find((task) => task.status === "running" && task.plan_step_id);
  if (runningTask?.plan_step_id) {
    const step = plan.find((item) => item.id === runningTask.plan_step_id);
    if (step) {
      const index = typeof step.step_index === "number" ? step.step_index + 1 : plan.indexOf(step) + 1;
      return {
        title: step.title,
        index,
        total,
        requiresApproval: Boolean(step.requires_approval)
      };
    }
  }
  const fallback = plan.find((step) => step.status !== "done" && step.status !== "canceled" && step.status !== "failed") || plan[0];
  const index = typeof fallback.step_index === "number" ? fallback.step_index + 1 : plan.indexOf(fallback) + 1;
  return {
    title: fallback.title,
    index,
    total,
    requiresApproval: Boolean(fallback.requires_approval)
  };
}

export default function OverlayApp() {
  const [overlayMode, setOverlayMode] = useState<OverlayMode>(() => getStoredOverlayMode());
  const [runId, setRunId] = useState<string | null>(() => getStoredRunId());
  const [run, setRun] = useState<Run | null>(null);
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [streamState, setStreamState] = useState<"idle" | "live" | "reconnecting" | "polling">("idle");

  const eventsRef = useRef<EventItem[]>([]);
  const lastSeqRef = useRef<number>(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const refreshTimerRef = useRef<number | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);

  const pendingApproval = approvals.find((approval) => approval.status === "pending") || null;
  const stepSummary = useMemo(() => selectActiveStep(plan, tasks), [plan, tasks]);
  const errorCount = useMemo(
    () => events.filter((event) => event.level === "error" || event.type.includes("failed")).length,
    [events]
  );
  const overlayStatus = useMemo(
    () => deriveOverlayStatus(run?.status, Boolean(pendingApproval), errorCount > 0),
    [errorCount, pendingApproval, run?.status]
  );

  const pushEvents = useCallback((incoming: EventItem[] | null | undefined) => {
    if (!incoming?.length) return;
    const result = mergeEvents(eventsRef.current, incoming, EVENT_BUFFER_LIMIT);
    eventsRef.current = result.events;
    lastSeqRef.current = result.lastSeq;
    setEvents(result.events);
  }, []);

  const refreshSnapshot = useCallback(
    async (targetRunId: string) => {
      const snapshot = await getSnapshot(targetRunId);
      setRun(snapshot.run);
      setPlan(snapshot.plan || []);
      setTasks(snapshot.tasks || []);
      setApprovals(snapshot.approvals || []);
      pushEvents(snapshot.last_events || []);
      return snapshot;
    },
    [pushEvents]
  );

  const refreshSnapshotSafe = useCallback(
    async (targetRunId: string) => {
      try {
        await refreshSnapshot(targetRunId);
      } catch {
        setStreamState("polling");
      }
    },
    [refreshSnapshot]
  );

  const queueSnapshotRefresh = useCallback(
    (targetRunId: string, delay = 600) => {
      if (refreshTimerRef.current) return;
      refreshTimerRef.current = window.setTimeout(() => {
        refreshTimerRef.current = null;
        void refreshSnapshotSafe(targetRunId);
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
    (targetRunId: string) => {
      if (pollTimerRef.current) return;
      setStreamState("polling");
      pollTimerRef.current = window.setInterval(() => {
        void refreshSnapshotSafe(targetRunId);
      }, 5000);
    },
    [refreshSnapshotSafe]
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

  const openEventStream = useCallback(
    async (targetRunId: string) => {
      cleanupEventStream();
      stopPolling();
      const token = getSessionToken();
      if (!token) {
        await initAuth();
      }
      const safeToken = getSessionToken();
      const url = new URL(`${apiBase()}/runs/${targetRunId}/events`);
      if (safeToken) {
        url.searchParams.set("token", safeToken);
      }
      if (lastSeqRef.current) {
        url.searchParams.set("last_event_id", String(lastSeqRef.current));
      }
      const es = new EventSource(url.toString());
      es.onopen = () => {
        setStreamState("live");
        stopPolling();
        queueSnapshotRefresh(targetRunId, 0);
      };
      es.onerror = () => {
        setStreamState("reconnecting");
        es.close();
        startPolling(targetRunId);
      };
      EVENT_TYPES.forEach((type) => {
        es.addEventListener(type, (evt) => {
          try {
            const event = JSON.parse((evt as MessageEvent).data) as EventItem;
            pushEvents([event]);
            queueSnapshotRefresh(targetRunId, type.includes("run_") ? 0 : 700);
          } catch {
            setStreamState("polling");
          }
        });
      });
      eventSourceRef.current = es;
    },
    [cleanupEventStream, pushEvents, queueSnapshotRefresh, startPolling, stopPolling]
  );

  const handleOpenInspector = useCallback(() => {
    const tab = pendingApproval ? "approvals" : "steps";
    void invoke("open_main_window", { tab });
  }, [pendingApproval]);

  const handleToggleMode = useCallback(
    (mode: OverlayMode) => {
      setOverlayMode(mode);
      localStorage.setItem(OVERLAY_MODE_KEY, mode);
      void invoke("overlay_set_mode", { mode });
      if (mode === "off") {
        void invoke("overlay_hide");
      } else {
        void invoke("overlay_show");
      }
    },
    []
  );

  useEffect(() => {
    const handler = (event: StorageEvent) => {
      if (event.key === LAST_RUN_KEY) {
        setRunId(event.newValue);
      }
      if (event.key === OVERLAY_MODE_KEY && event.newValue) {
        const next = event.newValue as OverlayMode;
        setOverlayMode(next);
      }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  useEffect(() => {
    if (!runId) return;
    void refreshSnapshotSafe(runId);
    void openEventStream(runId);
    return () => cleanupEventStream();
  }, [cleanupEventStream, openEventStream, refreshSnapshotSafe, runId]);

  const handlePauseResume = useCallback(async () => {
    if (!run) return;
    if (run.status === "running") {
      await pauseRun(run.id);
    } else if (run.status === "paused" || (run.status || "").includes("waiting")) {
      await resumeRun(run.id);
    }
    await refreshSnapshotSafe(run.id);
  }, [refreshSnapshotSafe, run]);

  const handleStop = useCallback(async () => {
    if (!run) return;
    await cancelRun(run.id);
    await refreshSnapshotSafe(run.id);
  }, [refreshSnapshotSafe, run]);

  return (
    <div className="overlay-shell" onClick={handleOpenInspector}>
      <div className="overlay-left">
        <div className={`overlay-status ${overlayStatus.tone}`}>{overlayStatus.label}</div>
        <div className="overlay-step">
          {stepSummary ? stepSummary.title : run ? "Нет активного шага" : "Нет активного run"}
        </div>
        <div className="overlay-meta">
          {stepSummary ? `Шаг ${stepSummary.index}/${stepSummary.total}` : "—"}
          {pendingApproval ? " · approval" : stepSummary?.requiresApproval ? " · риск" : ""}
          <span className="overlay-stream">{streamState === "live" ? "SSE" : ""}</span>
        </div>
      </div>
      <div className="overlay-actions" onClick={(event) => event.stopPropagation()}>
        <div className="overlay-modes">
          {(["auto", "pinned", "off"] as OverlayMode[]).map((mode) => (
            <button
              key={mode}
              className={`btn ghost tiny ${overlayMode === mode ? "active" : ""}`}
              onClick={() => handleToggleMode(mode)}
            >
              {mode === "auto" ? "Auto" : mode === "pinned" ? "Pin" : "Off"}
            </button>
          ))}
        </div>
        <div className="overlay-controls">
          {run ? (
            <>
              <button className="btn ghost tiny" onClick={handlePauseResume}>
                {run.status === "running" ? "Pause" : "Resume"}
              </button>
              <button className="btn danger tiny" onClick={handleStop}>
                Stop
              </button>
            </>
          ) : null}
          <button className="btn primary tiny" onClick={handleOpenInspector}>
            Open
          </button>
        </div>
      </div>
    </div>
  );
}
