import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  apiBase,
  listProjects,
  createProject,
  createRun,
  createPlan,
  startRun,
  cancelRun,
  pauseRun,
  resumeRun,
  getSnapshot,
  initAuth,
  getSessionToken,
  checkPermissions,
  approve,
  reject,
  resolveConflict,
  searchMemory,
  retryTask,
  retryStep,
  downloadArtifact,
  downloadSnapshot
} from "./api";
import { ru } from "./i18n/ru";
import { listen } from "@tauri-apps/api/event";

const t = ru;
const isOverlay = new URLSearchParams(window.location.search).get("overlay") === "1";

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
  "autopilot_state"
];

// EN kept: значения режимов — публичный контракт API
const MODE_OPTIONS = [
  { value: "plan_only", label: t.modes.plan_only },
  { value: "research", label: t.modes.research },
  { value: "execute_confirm", label: t.modes.execute_confirm },
  { value: "autopilot_safe", label: t.modes.autopilot_safe }
];

function label(map: Record<string, string>, key: string, fallback: string) {
  return map[key] || fallback;
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

function MainView() {
  const [view, setView] = useState<"onboarding" | "projects" | "workspace">("onboarding");
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<any | null>(null);
  const [run, setRun] = useState<any | null>(null);
  const [plan, setPlan] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [sources, setSources] = useState<any[]>([]);
  const [facts, setFacts] = useState<any[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any | null>(null);
  const [autopilotState, setAutopilotState] = useState<any | null>(null);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryResults, setMemoryResults] = useState<any[]>([]);
  const [queryText, setQueryText] = useState("");
  const [mode, setMode] = useState("research");
  const [rightTab, setRightTab] = useState<"sources" | "facts" | "artifacts" | "conflicts" | "memory">("sources");
  const [projectName, setProjectName] = useState("");
  const [projectTags, setProjectTags] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<any | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const refreshLock = useRef(false);

  useEffect(() => {
    initAuth()
      .then(loadProjects)
      .catch((err) => setStatus(err.message || t.errors.authInit));
  }, []);

  useEffect(() => {
    if (view !== "onboarding") return;
    checkPermissions()
      .then(setPermissions)
      .catch(() => setPermissions(null));
  }, [view]);

  useEffect(() => {
    const unlisten = listen("autopilot_stop_hotkey", async () => {
      if (run) {
        await cancelRun(run.id);
        await refreshSnapshot(run.id);
      }
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [run]);

  async function loadProjects() {
    const data = await listProjects();
    setProjects(data);
    if (data.length > 0 && view === "onboarding") {
      setView("projects");
    }
  }

  async function handleCreateProject() {
    if (!projectName.trim()) return;
    const tags = projectTags.split(",").map((t) => t.trim()).filter(Boolean);
    const project = await createProject({ name: projectName.trim(), tags, settings: {} });
    setProjects((prev) => [project, ...prev]);
    setProjectName("");
    setProjectTags("");
  }

  function openProject(project: any) {
    setSelectedProject(project);
    setView("workspace");
    setRun(null);
    setPlan([]);
    setTasks([]);
    setSources([]);
    setFacts([]);
    setConflicts([]);
    setArtifacts([]);
    setApprovals([]);
    setEvents([]);
    setMetrics(null);
  }

  async function handleCreateRun() {
    if (!selectedProject || !queryText.trim()) return;
    const newRun = await createRun(selectedProject.id, { query_text: queryText, mode });
    setRun(newRun);
    localStorage.setItem("astra_last_run_id", newRun.id);
    setEvents([]);
    setPlan([]);
    setTasks([]);
    setSources([]);
    setFacts([]);
    setConflicts([]);
    setArtifacts([]);
    setApprovals([]);
    setMetrics(null);
  }

  async function handleRunCommand() {
    if (!selectedProject || !queryText.trim()) return;
    const newRun = await createRun(selectedProject.id, { query_text: queryText, mode });
    setRun(newRun);
    localStorage.setItem("astra_last_run_id", newRun.id);
    setEvents([]);
    setPlan([]);
    setTasks([]);
    setSources([]);
    setFacts([]);
    setConflicts([]);
    setArtifacts([]);
    setApprovals([]);
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
  }

  async function handleRetryTask(taskId: string) {
    if (!run) return;
    await retryTask(run.id, taskId);
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

  async function handleApprove(approvalId: string, decision?: { limit?: number; action?: string }) {
    await approve(approvalId, decision);
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
      setEvents((prev) => [payload, ...prev].slice(0, 500));
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
    setSources(snapshot.sources || []);
    setFacts(snapshot.facts || []);
    setConflicts(snapshot.conflicts || []);
    setArtifacts(snapshot.artifacts || []);
    setApprovals(snapshot.approvals || []);
    setMetrics(snapshot.metrics || null);
  }

  async function handleMemorySearch() {
    if (!selectedProject || !memoryQuery.trim()) return;
    const results = await searchMemory(selectedProject.id, memoryQuery.trim());
    setMemoryResults(results || []);
  }

  const pendingApprovals = useMemo(() => approvals.filter((a) => a.status === "pending"), [approvals]);
  const planById = useMemo(() => new Map(plan.map((step) => [step.id, step])), [plan]);
  const reportArtifact = useMemo(() => artifacts.find((a) => a.type === "report_md"), [artifacts]);

  return (
    <div className="app">
      <header className="brand">
        <div>
          <div className="brand-title">{t.brand.title}</div>
          <div className="brand-sub">{t.brand.subtitle}</div>
        </div>
        <div className="brand-status">{t.brand.api}: {apiBase()}</div>
      </header>

      {view === "onboarding" && (
        <section className="panel onboarding">
          <h2>{t.onboarding.title}</h2>
          <p>{t.onboarding.storage}</p>
          <div className="onboarding-grid">
            <div>
              <h3>{t.onboarding.providerTitle}</h3>
              <p>{t.onboarding.providerText}</p>
              <code>{t.onboarding.providerCommand}</code>
            </div>
            <div>
              <h3>{t.onboarding.vaultTitle}</h3>
              <p>{t.onboarding.vaultText}</p>
            </div>
            <div>
              <h3>{t.onboarding.permissionsTitle}</h3>
              <p>{permissions ? permissions.message : t.onboarding.permissionsUnknown}</p>
              <div className="row">
                <button onClick={async () => setPermissions(await checkPermissions())}>{t.onboarding.permissionsCheck}</button>
              </div>
            </div>
            <div>
              <h3>{t.onboarding.nextTitle}</h3>
              <button className="primary" onClick={() => setView("projects")}>{t.onboarding.continue}</button>
            </div>
          </div>
        </section>
      )}

      {view === "projects" && (
        <section className="panel projects">
          <h2>{t.projects.title}</h2>
          <div className="projects-grid">
            <div className="projects-list">
              {projects.map((project) => (
                <button key={project.id} className="project-card" onClick={() => openProject(project)}>
                  <div className="project-name">{project.name}</div>
                  <div className="project-tags">{(project.tags || []).join(" · ") || t.projects.noTags}</div>
                </button>
              ))}
            </div>
            <div className="project-create">
              <h3>{t.projects.createTitle}</h3>
              <input
                type="text"
                placeholder={t.projects.namePlaceholder}
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
              />
              <input
                type="text"
                placeholder={t.projects.tagsPlaceholder}
                value={projectTags}
                onChange={(e) => setProjectTags(e.target.value)}
              />
              <button className="primary" onClick={handleCreateProject}>{t.projects.createButton}</button>
            </div>
          </div>
        </section>
      )}

      {view === "workspace" && selectedProject && (
        <section className="workspace">
          <div className="topbar">
            <div>
              <div className="project-title">{selectedProject.name}</div>
              <div className="project-meta">
                {t.labels.mode}: {label(t.modes, mode, mode)} · {t.labels.run}: {run ? label(t.runStatus, run.status, run.status) : t.labels.statusIdle}
              </div>
              <div className="badges">
                <span className="badge">{t.labels.coverage} {formatCoverage(metrics)}</span>
                <span className="badge">{t.labels.conflicts} {metrics?.conflicts ?? 0}</span>
                <span className="badge">{t.labels.freshness} {formatFreshness(metrics)}</span>
                <span className="badge">{t.labels.approvals} {pendingApprovals.length}</span>
              </div>
            </div>
            <div className="topbar-actions">
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODE_OPTIONS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <button className="ghost" onClick={handleCancelRun}>{t.workspace.stopRun}</button>
              <button onClick={handleExportSnapshot} disabled={!run}>{t.workspace.exportJson}</button>
              <button onClick={handleExportReport} disabled={!reportArtifact}>{t.workspace.exportMd}</button>
            </div>
          </div>

          <div className="workspace-grid">
            <div className="column">
              <div className="panel">
                <h3>{t.workspace.queryTitle}</h3>
                <textarea
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  placeholder={t.workspace.queryPlaceholder}
                />
                <div className="row">
                  <button className="primary" onClick={handleRunCommand}>{t.workspace.createRun}</button>
                  <button onClick={handleCreatePlan} disabled={!run}>{t.workspace.createPlan}</button>
                  <button onClick={handleStartRun} disabled={!run}>{t.workspace.startRun}</button>
                </div>
              </div>
              <div className="panel">
                <h3>{t.workspace.planTitle}</h3>
                <ul className="list">
                  {plan.map((step) => (
                    <li key={step.id}>
                      <div className="list-title">{step.step_index + 1}. {step.title}</div>
                      <div className="list-sub">{label(t.skills, step.skill_name, step.skill_name)} · {label(t.stepStatus, step.status, step.status)}</div>
                      <div className="row">
                        <button onClick={() => handleRetryStep(step.id)} disabled={!run}>{t.workspace.retryStep}</button>
                      </div>
                    </li>
                  ))}
                  {!plan.length && <li>{t.empty.plan}</li>}
                </ul>
              </div>
            </div>

            <div className="column">
              <div className="panel">
                <h3>{t.workspace.tasksTitle}</h3>
                <ul className="list">
                  {tasks.map((task) => {
                    const step = planById.get(task.plan_step_id);
                    return (
                      <li key={task.id}>
                        <div className="list-title">{label(t.taskStatus, task.status, task.status)}</div>
                        <div className="list-sub">{step ? `${step.step_index + 1}. ${step.title}` : task.plan_step_id}</div>
                        {task.status === "failed" && (
                          <div className="row">
                            <button onClick={() => handleRetryTask(task.id)}>{t.workspace.retryTask}</button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                  {!tasks.length && <li>{t.empty.tasks}</li>}
                </ul>
              </div>
              <div className="panel">
                <h3>{t.workspace.approvalsTitle}</h3>
                <ul className="list">
                  {approvals.map((approval) => (
                    <li key={approval.id}>
                      <div className="list-title">{approval.title}</div>
                      <div className="list-sub">{label(t.approvalScope, approval.scope, approval.scope)} · {label(t.approvalStatus, approval.status, approval.status)}</div>
                      {approval.description && <div className="list-sub">{approval.description}</div>}
                      {approval.proposed_actions?.[0]?.preview_tracks?.length > 0 && (
                        <ul className="list">
                          {approval.proposed_actions[0].preview_tracks.map((track: any, idx: number) => (
                            <li key={`${approval.id}-preview-${idx}`}>
                              <div className="list-title">{track.artist} — {track.title}</div>
                            </li>
                          ))}
                        </ul>
                      )}
                      {approval.status === "pending" && (
                        <div className="row">
                          {approval.scope === "login" ? (
                            <button onClick={() => handleApprove(approval.id)}>{t.workspace.approveContinue}</button>
                          ) : (
                            <button onClick={() => handleApprove(approval.id)}>{t.workspace.approve}</button>
                          )}
                          {approval.proposed_actions?.[0]?.limit_options?.includes(50) && (
                            <button onClick={() => handleApprove(approval.id, { limit: 50 })}>{t.workspace.approveLimit50}</button>
                          )}
                          {approval.proposed_actions?.[0]?.limit_options?.includes(100) && (
                            <button onClick={() => handleApprove(approval.id, { limit: 100 })}>{t.workspace.approveLimit100}</button>
                          )}
                          <button className="danger" onClick={() => handleReject(approval.id)}>{t.workspace.reject}</button>
                        </div>
                      )}
                    </li>
                  ))}
                  {!approvals.length && <li>{t.empty.approvals}</li>}
                </ul>
              </div>
            </div>

            <div className="column">
              <div className="panel">
                <div className="row">
                  {Object.entries(t.rightTabs).map(([key, labelText]) => (
                    <button
                      key={key}
                      className={rightTab === key ? "primary" : "ghost"}
                      onClick={() => setRightTab(key as any)}
                    >
                      {labelText}
                    </button>
                  ))}
                </div>
              </div>
              {rightTab === "sources" && (
                <div className="panel">
                  <h3>{t.workspace.sourcesTitle}</h3>
                  <ul className="list">
                    {sources.map((source) => (
                      <li key={source.id}>
                        <div className="list-title">{source.title || source.url}</div>
                        <div className="list-sub">{source.domain || t.quality.unknown} · {label(t.quality, source.quality || "unknown", source.quality || "unknown")}</div>
                      </li>
                    ))}
                    {!sources.length && <li>{t.empty.sources}</li>}
                  </ul>
                </div>
              )}
              {rightTab === "facts" && (
                <div className="panel">
                  <h3>{t.workspace.factsTitle}</h3>
                  <ul className="list">
                    {facts.map((fact) => (
                      <li key={fact.id}>
                        <div className="list-title">{fact.key}</div>
                        <div className="list-sub">{JSON.stringify(fact.value)}</div>
                      </li>
                    ))}
                    {!facts.length && <li>{t.empty.facts}</li>}
                  </ul>
                </div>
              )}
              {rightTab === "artifacts" && (
                <div className="panel">
                  <h3>{t.workspace.artifactsTitle}</h3>
                  <ul className="list">
                    {artifacts.map((artifact) => (
                      <li key={artifact.id}>
                        <div className="list-title">{artifact.title}</div>
                        <div className="list-sub">{label(t.artifactTypes, artifact.type, artifact.type)}</div>
                        <div className="row">
                          <button onClick={async () => downloadBlob(await downloadArtifact(artifact.id), artifact.title || "артефакт")}>{t.labels.artifactsDownload}</button>
                        </div>
                      </li>
                    ))}
                    {!artifacts.length && <li>{t.empty.artifacts}</li>}
                  </ul>
                </div>
              )}
              {rightTab === "conflicts" && (
                <div className="panel">
                  <h3>{t.workspace.conflictsTitle}</h3>
                  <ul className="list">
                    {conflicts.map((conflict) => (
                      <li key={conflict.id}>
                        <div className="list-title">{conflict.fact_key}</div>
                        <div className="list-sub">{label(t.conflictStatus, conflict.status, conflict.status)}</div>
                        <div className="row">
                          <button onClick={() => run && resolveConflict(run.id, conflict.id)}>{t.workspace.resolveConflict}</button>
                        </div>
                      </li>
                    ))}
                    {!conflicts.length && <li>{t.empty.conflicts}</li>}
                  </ul>
                </div>
              )}
              {rightTab === "memory" && (
                <div className="panel">
                  <h3>{t.workspace.memoryTitle}</h3>
                  <div className="row">
                    <input
                      type="text"
                      placeholder={t.workspace.memoryPlaceholder}
                      value={memoryQuery}
                      onChange={(e) => setMemoryQuery(e.target.value)}
                    />
                    <button onClick={handleMemorySearch}>{t.workspace.search}</button>
                  </div>
                  <ul className="list">
                    {memoryResults.map((res, idx) => (
                      <li key={`${res.type}-${idx}`}>
                        <div className="list-title">{label(t.memoryTypes, res.type, res.type)}</div>
                        <div className="list-sub">{JSON.stringify(res.item)}</div>
                      </li>
                    ))}
                    {!memoryResults.length && <li>{t.empty.memory}</li>}
                  </ul>
                </div>
              )}
            </div>
          </div>

          <div className="panel events">
            <h3>{t.workspace.eventsTitle}</h3>
            <ul className="list">
              {events.map((evt) => (
                <li key={`${evt.id}-${evt.seq}`}>
                  <div className="list-title">{label(t.events, evt.type, evt.type)}</div>
                  <div className="list-sub">{evt.message}</div>
                </li>
              ))}
              {!events.length && <li>{t.empty.events}</li>}
            </ul>
          </div>
        </section>
      )}

      {status && <div className="status">{status}</div>}
    </div>
  );
}

function OverlayView() {
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>("idle");
  const [autopilotState, setAutopilotState] = useState<any | null>(null);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    initAuth()
      .then(() => {
        const last = localStorage.getItem("astra_last_run_id");
        if (last) {
          setRunId(last);
          refreshSnapshot(last);
          openEventStream(last);
        }
      })
      .catch((err) => setStatus(err.message || t.errors.authInit));
  }, []);

  useEffect(() => {
    document.body.classList.add("overlay-mode");
    return () => {
      document.body.classList.remove("overlay-mode");
    };
  }, []);

  async function refreshSnapshot(id: string) {
    try {
      const snapshot = await getSnapshot(id);
      setRunStatus(snapshot.run?.status || "idle");
      setApprovals(snapshot.approvals || []);
    } catch (err: any) {
      setStatus(err.message || "Ошибка снимка");
    }
  }

  function openEventStream(id: string) {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    const token = getSessionToken();
    const es = new EventSource(`${apiBase()}/runs/${id}/events?token=${token}`);
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
      if (runId) {
        await refreshSnapshot(runId);
      }
    } catch {
      setStatus(t.errors.parseEvent);
    }
  }

  async function handleStop() {
    if (!runId) return;
    await cancelRun(runId);
    await refreshSnapshot(runId);
  }

  async function handlePauseToggle() {
    if (!runId) return;
    if (runStatus === "paused") {
      await resumeRun(runId);
    } else {
      await pauseRun(runId);
    }
    await refreshSnapshot(runId);
  }

  async function handleApprove(approvalId: string) {
    await approve(approvalId);
    if (runId) await refreshSnapshot(runId);
  }

  async function handleReject(approvalId: string) {
    await reject(approvalId);
    if (runId) await refreshSnapshot(runId);
  }

  const pending = approvals.filter((a) => a.status === "pending");
  const activeApproval = pending[0];

  const overlayStatus = autopilotState?.status || runStatus || "idle";
  const overlayStatusLabel = ({
    running: "Работает",
    waiting_confirm: "Ждёт подтверждение",
    needs_user: "Нужна помощь",
    done: "Завершено",
    failed: "Ошибка",
    paused: "Пауза",
    idle: "Ожидание",
  } as Record<string, string>)[overlayStatus] || label(t.runStatus, overlayStatus, overlayStatus);

  const actionLabel = (value: string) => ({
    move_mouse: "Перемещение мыши",
    click: "Клик",
    double_click: "Двойной клик",
    drag: "Перетаскивание",
    type: "Ввод текста",
    key: "Горячие клавиши",
    scroll: "Прокрутка",
    wait: "Ожидание",
  } as Record<string, string>)[value] || value;

  return (
    <div className={`overlay ${expanded ? "expanded" : "collapsed"}`} onDoubleClick={() => setExpanded(!expanded)}>
      <div className="overlay-header">
        <div className="overlay-brand">
          <div className="overlay-title">Randarc-Astra</div>
          <div className={`overlay-status-pill status-${overlayStatus}`}>{overlayStatusLabel}</div>
        </div>
        <div className="overlay-controls">
          <button className="ghost" onClick={() => setExpanded(!expanded)}>{expanded ? "Свернуть" : "Развернуть"}</button>
          <button className="danger" onClick={handleStop}>Стоп</button>
        </div>
      </div>
      {expanded && (
        <div className="overlay-body">
          <div className="overlay-block">
            <div className="overlay-label">{t.labels.overlayGoal}</div>
            <div className="overlay-value">{autopilotState?.goal || "—"}</div>
          </div>
          <div className="overlay-block">
            <div className="overlay-label">{t.labels.overlayStep}</div>
            <div className="overlay-value">{autopilotState?.step_summary || "—"}</div>
          </div>
          <div className="overlay-block">
            <div className="overlay-label">{t.labels.overlayReason}</div>
            <div className="overlay-value">{autopilotState?.reason || "—"}</div>
          </div>
          <div className="overlay-block">
            <div className="overlay-label">{t.labels.overlayPlan}</div>
            <ul className="overlay-plan">
              {(autopilotState?.plan || []).slice(0, 5).map((item: string, idx: number) => (
                <li key={`plan-${idx}`}>{item}</li>
              ))}
              {(!autopilotState?.plan || autopilotState.plan.length === 0) && <li>—</li>}
            </ul>
          </div>
          <div className="overlay-block">
            <div className="overlay-label">{t.labels.overlayActions}</div>
            <div className="overlay-actions">
              {(autopilotState?.actions || []).slice(0, 8).map((action: any, idx: number) => (
                <span key={`action-${idx}`} className="overlay-chip">{actionLabel(action.type)}</span>
              ))}
              {(!autopilotState?.actions || autopilotState.actions.length === 0) && <span className="overlay-chip muted">—</span>}
            </div>
          </div>
          <div className="overlay-footer">
            <button onClick={handlePauseToggle}>{runStatus === "paused" ? "Продолжить" : "Пауза"}</button>
            {activeApproval && (
              <>
                <button className="primary" onClick={() => handleApprove(activeApproval.id)}>Подтвердить</button>
                <button className="danger" onClick={() => handleReject(activeApproval.id)}>Отклонить</button>
              </>
            )}
          </div>
          {status && <div className="overlay-toast">{status}</div>}
        </div>
      )}
    </div>
  );
}

function App() {
  return isOverlay ? <OverlayView /> : <MainView />;
}

export default App;
