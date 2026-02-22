import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Brain,
  Bot,
  CheckCircle2,
  Circle,
  Clock3,
  Globe,
  Info,
  Loader2,
  Pause,
  PanelRightClose,
  Search,
  Square,
  Layers
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "../shared/utils/cn";
import Badge from "../shared/ui/Badge";
import Button from "../shared/ui/Button";
import IconButton from "../shared/ui/IconButton";
import Tooltip from "../shared/ui/Tooltip";
import { phaseLabel, stepLabel, useAppStore } from "../shared/store/appStore";
import type { EventItem } from "../shared/types/api";
import type { ActivityStepStatus } from "../shared/types/ui";

export type ActivityPanelProps = {
  open: boolean;
  width: number;
  resizing: boolean;
  onToggle: () => void;
};

const STYLE_DEBUG_STORAGE_KEY = "astra.ui.debug.styleMeta";

const statusTone: Record<ActivityStepStatus, "success" | "warn" | "muted" | "danger"> = {
  done: "success",
  active: "warn",
  pending: "muted",
  error: "danger"
};

const statusIcon: Record<ActivityStepStatus, ReactNode> = {
  done: <CheckCircle2 size={16} />,
  active: <Loader2 size={16} className="spin" />,
  pending: <Circle size={16} />,
  error: <AlertTriangle size={16} />
};

type ThoughtTone = "neutral" | "active" | "success" | "warn" | "error";

type ThoughtLine = {
  id: string;
  title: string;
  detail?: string;
  tone: ThoughtTone;
  icon: ReactNode;
  ts?: number;
  live?: boolean;
};

function payloadString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function payloadNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function eventTimeLabel(ts?: number): string {
  if (!ts) return "";
  const normalized = ts < 1e12 ? ts * 1000 : ts;
  return new Date(normalized).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function loadStyleDebugFlag() {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STYLE_DEBUG_STORAGE_KEY) === "1";
}

function thoughtFromEvent(event: EventItem): ThoughtLine | null {
  const payload = (event.payload || {}) as Record<string, unknown>;
  const seq = event.seq ?? event.id;
  const type = event.type;

  if (type === "intent_decided") {
    const intent = payloadString(payload, "intent") || "UNKNOWN";
    const reasons = Array.isArray(payload.reasons)
      ? (payload.reasons as unknown[]).filter((item): item is string => typeof item === "string").slice(0, 3).join(", ")
      : "";
    return {
      id: `thought-${seq}`,
      title: `Определяю интент: ${intent}`,
      detail: reasons || undefined,
      tone: "active",
      icon: <Brain size={15} />,
      ts: event.ts,
      live: true
    };
  }

  if (type === "llm_route_decided") {
    const route = payloadString(payload, "route") || "LOCAL";
    const model = payloadString(payload, "model_id") || "model";
    const reason = payloadString(payload, "reason");
    return {
      id: `thought-${seq}`,
      title: `Маршрут LLM: ${route}`,
      detail: reason ? `${model} • ${reason}` : model,
      tone: "neutral",
      icon: <Bot size={15} />,
      ts: event.ts
    };
  }

  if (type === "llm_request_started") {
    const model = payloadString(payload, "model_id") || "model";
    return {
      id: `thought-${seq}`,
      title: "Запрос к модели",
      detail: model,
      tone: "active",
      icon: <Loader2 size={15} className="spin" />,
      ts: event.ts,
      live: true
    };
  }

  if (type === "llm_request_succeeded") {
    const model = payloadString(payload, "model_id") || "model";
    const latency = payloadNumber(payload, "latency_ms");
    return {
      id: `thought-${seq}`,
      title: "Модель ответила",
      detail: latency != null ? `${model} • ${latency} ms` : model,
      tone: "success",
      icon: <CheckCircle2 size={15} />,
      ts: event.ts
    };
  }

  if (type === "llm_request_failed" || type === "local_llm_http_error") {
    const errorType = payloadString(payload, "error_type") || payloadString(payload, "status") || event.message;
    return {
      id: `thought-${seq}`,
      title: "Ошибка запроса к модели",
      detail: errorType || undefined,
      tone: "error",
      icon: <AlertTriangle size={15} />,
      ts: event.ts
    };
  }

  if (type === "task_progress") {
    const phase = payloadString(payload, "phase");
    if (phase === "chat_auto_web_research_started") {
      return {
        id: `thought-${seq}`,
        title: "Проверяю данные в интернете",
        detail: payloadString(payload, "query") || undefined,
        tone: "active",
        icon: <Globe size={15} />,
        ts: event.ts,
        live: true
      };
    }
    if (phase === "chat_auto_web_research_done") {
      const sources = payloadNumber(payload, "sources_count");
      const latency = payloadNumber(payload, "latency_ms");
      const detail = [
        sources != null ? `источников: ${sources}` : null,
        latency != null ? `${latency} ms` : null
      ]
        .filter(Boolean)
        .join(" • ");
      return {
        id: `thought-${seq}`,
        title: "Web research завершен",
        detail: detail || undefined,
        tone: "success",
        icon: <CheckCircle2 size={15} />,
        ts: event.ts
      };
    }
    if (phase === "chat_auto_web_research_failed") {
      return {
        id: `thought-${seq}`,
        title: "Web research не удался",
        detail: payloadString(payload, "error") || undefined,
        tone: "error",
        icon: <AlertTriangle size={15} />,
        ts: event.ts
      };
    }
    if (phase === "chat_auto_web_research_off_topic") {
      return {
        id: `thought-${seq}`,
        title: "Web research не по теме запроса",
        detail: payloadString(payload, "query") || undefined,
        tone: "warn",
        icon: <AlertTriangle size={15} />,
        ts: event.ts
      };
    }

    const reasonCode = payloadString(payload, "reason_code");
    const query = payloadString(payload, "query");
    const detail = [reasonCode, query].filter(Boolean).join(" • ");
    return {
      id: `thought-${seq}`,
      title: event.message || "Прогресс задачи",
      detail: detail || undefined,
      tone: "active",
      icon: <Search size={15} />,
      ts: event.ts,
      live: true
    };
  }

  if (type === "source_found" || type === "source_fetched") {
    const url = payloadString(payload, "url");
    const count = payloadNumber(payload, "count");
    return {
      id: `thought-${seq}`,
      title: type === "source_found" ? "Найден источник" : "Источники сохранены",
      detail: url || (count != null ? `количество: ${count}` : undefined),
      tone: "neutral",
      icon: <Globe size={15} />,
      ts: event.ts
    };
  }

  if (type === "chat_response_generated") {
    const provider = payloadString(payload, "provider") || "local";
    const sources = payloadNumber(payload, "sources_count");
    const detail = provider === "web_research" && sources != null ? `источников: ${sources}` : provider;
    return {
      id: `thought-${seq}`,
      title: provider === "web_research" ? "Формирую ответ по источникам" : "Формирую финальный ответ",
      detail,
      tone: "success",
      icon: <Bot size={15} />,
      ts: event.ts
    };
  }

  if (type === "approval_requested" || type === "step_paused_for_approval") {
    return {
      id: `thought-${seq}`,
      title: "Нужно подтверждение действия",
      detail: event.message || undefined,
      tone: "warn",
      icon: <Info size={15} />,
      ts: event.ts
    };
  }

  if (type === "run_done" || type === "task_done") {
    return {
      id: `thought-${seq}`,
      title: "Этап завершен",
      detail: event.message || undefined,
      tone: "success",
      icon: <CheckCircle2 size={15} />,
      ts: event.ts
    };
  }

  if (type === "run_failed" || type === "task_failed") {
    return {
      id: `thought-${seq}`,
      title: "Выполнение завершилось с ошибкой",
      detail: event.message || undefined,
      tone: "error",
      icon: <AlertTriangle size={15} />,
      ts: event.ts
    };
  }

  return null;
}

export default function ActivityPanel({ open, width, resizing, onToggle }: ActivityPanelProps) {
  const activity = useAppStore((state) => state.activity);
  const approvals = useAppStore((state) => state.approvals);
  const detailed = useAppStore((state) => state.activityDetailed);
  const setDetailed = useAppStore((state) => state.setActivityDetailed);
  const pauseActiveRun = useAppStore((state) => state.pauseActiveRun);
  const cancelActiveRun = useAppStore((state) => state.cancelActiveRun);
  const streamState = useAppStore((state) => state.streamState);
  const currentRun = useAppStore((state) => state.currentRun);
  const events = useAppStore((state) => state.events);
  const overlayOpen = useAppStore((state) => state.overlayOpen);
  const setOverlayOpen = useAppStore((state) => state.setOverlayOpen);
  const [styleDebug, setStyleDebug] = useState(loadStyleDebugFlag);

  const phase = activity ? phaseLabel(activity.phase) : "Планирую";
  const pendingApproval = approvals.find((item) => item.status === "pending");
  const canPause = currentRun?.status === "running";
  const canStop =
    currentRun?.status === "running" || currentRun?.status === "paused" || currentRun?.status === "planning";
  const errorEvent = useMemo(() => {
    return [...events].reverse().find((event) => event.type === "local_llm_http_error");
  }, [events]);
  const thoughtLines = useMemo(() => {
    const runId = currentRun?.id || null;
    const filtered = runId ? events.filter((event) => !event.run_id || event.run_id === runId) : events;
    const lines = filtered.map((event) => thoughtFromEvent(event)).filter((item): item is ThoughtLine => Boolean(item));
    return lines.slice(-18).reverse();
  }, [currentRun?.id, events]);
  const selectedStyleMeta = useMemo(() => {
    const runMeta = currentRun?.meta;
    if (!runMeta || typeof runMeta !== "object") return null;
    const raw = (runMeta as Record<string, unknown>).selected_response_style_meta;
    if (!raw || typeof raw !== "object") return null;
    const meta = raw as Record<string, unknown>;
    const selectedStyle =
      typeof meta.selected_style === "string" && meta.selected_style.trim() ? meta.selected_style.trim() : null;
    const responseMode =
      typeof meta.response_mode === "string" && meta.response_mode.trim() ? meta.response_mode.trim() : null;
    const detailRequested = Boolean(meta.detail_requested);
    const sources = Array.isArray(meta.sources)
      ? meta.sources.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : [];
    if (!selectedStyle && !responseMode && sources.length === 0) return null;
    return { selectedStyle, responseMode, detailRequested, sources };
  }, [currentRun?.meta]);
  const artifactPath = useMemo(() => {
    const payload = errorEvent?.payload;
    if (payload && typeof payload === "object" && "artifact_path" in payload) {
      const value = payload.artifact_path;
      return typeof value === "string" ? value : null;
    }
    return null;
  }, [errorEvent]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STYLE_DEBUG_STORAGE_KEY, styleDebug ? "1" : "0");
  }, [styleDebug]);

  return (
    <aside
      className={cn("activity-panel", { "is-hidden": !open, "is-resizing": resizing })}
      style={{ width }}
    >
      <div className="activity-header">
        <div
          className="activity-title"
          onDoubleClick={(event) => {
            if (!event.altKey) return;
            setStyleDebug((prev) => !prev);
          }}
          title={styleDebug ? "Style debug: ON (Alt+DoubleClick чтобы выключить)" : undefined}
        >
          Активность
        </div>
        <div className="activity-actions">
          <IconButton
            type="button"
            size="sm"
            variant="subtle"
            aria-label="Пауза"
            onClick={() => void pauseActiveRun()}
            disabled={!canPause}
          >
            <Pause size={16} />
          </IconButton>
          <IconButton
            type="button"
            size="sm"
            variant="subtle"
            aria-label="Остановить"
            onClick={() => void cancelActiveRun()}
            disabled={!canStop}
          >
            <Square size={16} />
          </IconButton>
          <Tooltip label={overlayOpen ? "Скрыть оверлей" : "Показать оверлей"}>
            <span>
              <IconButton
                type="button"
                size="sm"
                variant="subtle"
                aria-label="Оверлей"
                onClick={() => setOverlayOpen(!overlayOpen)}
                active={overlayOpen}
              >
                <Layers size={16} />
              </IconButton>
            </span>
          </Tooltip>
          <IconButton type="button" size="sm" aria-label="Свернуть" onClick={onToggle}>
            <PanelRightClose size={16} />
          </IconButton>
        </div>
      </div>

      <AnimatePresence initial={false} mode="wait">
        {open ? (
          <motion.div
            key="activity-content"
            className="activity-content"
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 10 }}
            transition={{ duration: 0.2 }}
          >
            <div className="activity-phase">
              <div>
                <div className="activity-phase-label">Текущая фаза</div>
                <div className="activity-phase-title">{phase}</div>
              </div>
              <button
                type="button"
                className={cn("activity-toggle", { "is-active": detailed })}
                onClick={() => setDetailed(!detailed)}
              >
                {detailed ? "Подробно" : "Кратко"}
              </button>
            </div>

            {styleDebug ? (
              <div className="activity-debug">
                <Badge tone="muted" size="sm">
                  Style debug
                </Badge>
                {selectedStyleMeta ? (
                  <div className="activity-debug-lines">
                    {selectedStyleMeta.responseMode ? <div>mode: {selectedStyleMeta.responseMode}</div> : null}
                    <div>detail_requested: {selectedStyleMeta.detailRequested ? "true" : "false"}</div>
                    {selectedStyleMeta.sources.length ? (
                      <div>sources: {selectedStyleMeta.sources.join(", ")}</div>
                    ) : null}
                    {selectedStyleMeta.selectedStyle ? <div>style: {selectedStyleMeta.selectedStyle}</div> : null}
                  </div>
                ) : (
                  <div className="activity-debug-lines">style meta отсутствует для текущего run.</div>
                )}
              </div>
            ) : null}

            {streamState !== "live" ? (
              <div className="activity-connection">
                <Badge
                  tone={streamState === "reconnecting" ? "warn" : streamState === "offline" ? "danger" : "muted"}
                  size="sm"
                >
                  {streamState === "connecting"
                    ? "События: подключаюсь…"
                    : streamState === "reconnecting"
                      ? "События: переподключаюсь…"
                      : streamState === "offline"
                        ? "События: нет соединения"
                        : "События: ожидание"}
                </Badge>
              </div>
            ) : null}

            <div className="activity-steps">
              {activity?.steps?.length ? (
                activity.steps.map((step) => (
                  <motion.div
                    layout
                    key={step.id}
                    className="activity-step"
                    data-status={step.status}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                  >
                    <span className="activity-step-icon" data-status={step.status}>
                      {statusIcon[step.status]}
                    </span>
                    <span className="activity-step-title">{step.title}</span>
                    <Badge tone={statusTone[step.status]} size="sm">
                      {stepLabel(step.status)}
                    </Badge>
                  </motion.div>
                ))
              ) : (
                <div className="activity-empty">Шаги появятся после планирования.</div>
              )}
            </div>

            {detailed && activity?.details?.length ? (
              <div className="activity-details">
                {activity.details.map((line) => (
                  <div key={line} className="activity-detail-item">
                    {line}
                  </div>
                ))}
              </div>
            ) : null}

            <div className="activity-thinking">
              <div className="activity-thinking-header">Мышление и действия</div>
              {thoughtLines.length ? (
                <div className="activity-thinking-list">
                  {thoughtLines.map((line, index) => (
                    <motion.div
                      layout
                      key={line.id}
                      className={cn("activity-thought", `tone-${line.tone}`, { "is-live": line.live && index === 0 })}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.18, delay: Math.min(index * 0.015, 0.14) }}
                    >
                      <span className={cn("activity-thought-icon", `tone-${line.tone}`)}>{line.icon}</span>
                      <div className="activity-thought-body">
                        <div className="activity-thought-title">{line.title}</div>
                        {line.detail ? <div className="activity-thought-detail">{line.detail}</div> : null}
                      </div>
                      <span className="activity-thought-time">
                        <Clock3 size={12} />
                        {eventTimeLabel(line.ts)}
                      </span>
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="activity-empty">События мышления появятся после первого запроса.</div>
              )}
            </div>

            {pendingApproval ? (
              <div className="activity-approval">
                <div className="activity-approval-title">Требуется подтверждение</div>
                <div>{pendingApproval.title || "Нужен ответ перед продолжением работы."}</div>
                {pendingApproval.description ? (
                  <div className="activity-approval-detail">{pendingApproval.description}</div>
                ) : null}
              </div>
            ) : null}

            {errorEvent ? (
              <div className="activity-error">
                <div className="activity-error-title">Ошибка локальной модели</div>
                <div className="activity-error-text">
                  {errorEvent.message || "Проверьте параметры локальной модели."}
                </div>
                {artifactPath ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(artifactPath).catch(() => null);
                    }}
                  >
                    Показать детали
                  </Button>
                ) : null}
              </div>
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </aside>
  );
}
