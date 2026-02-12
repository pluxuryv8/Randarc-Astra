// EN kept: публичные пути API и заголовки HTTP — контракт интеграции
import { invoke } from "@tauri-apps/api/tauri";
import type {
  Approval,
  MemorySearchResult,
  UserMemory,
  Reminder,
  PlanStep,
  Project,
  ProjectSettings,
  Run,
  RunIntentResponse,
  Snapshot,
  StatusResponse
} from "./types";

const DEFAULT_PORT = import.meta.env.VITE_API_PORT || "8055";
const API_BASE = import.meta.env.VITE_API_BASE || `http://127.0.0.1:${DEFAULT_PORT}/api/v1`;
const SESSION_KEY = "astra_session_token";
let sessionToken: string | null = null;

type OpenAIStoreResponse = StatusResponse & { stored?: boolean };

export async function checkPermissions(): Promise<{ screen_recording: boolean; accessibility: boolean; message: string }> {
  return (await invoke("check_permissions")) as { screen_recording: boolean; accessibility: boolean; message: string };
}

function getOrCreateSessionToken(): string {
  if (sessionToken) return sessionToken;
  const stored = localStorage.getItem(SESSION_KEY);
  if (stored) {
    sessionToken = stored;
    return stored;
  }
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const token = Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  localStorage.setItem(SESSION_KEY, token);
  sessionToken = token;
  return token;
}

export async function initAuth(): Promise<string> {
  const token = getOrCreateSessionToken();
  const res = await fetch(`${API_BASE}/auth/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token })
  });
  if (!res.ok && res.status !== 409) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return token;
}

export async function checkApiStatus(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/auth/status`);
    return res.ok;
  } catch {
    return false;
  }
}

function authHeaders() {
  return (sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}) as Record<string, string>;
}

type ApiOptions = Omit<RequestInit, "headers"> & { headers?: Record<string, string> };

async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {})
    },
    ...options
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return {} as T;
  return (await res.json()) as T;
}

async function apiBlob(path: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders()
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return await res.blob();
}

export function listProjects(): Promise<Project[]> {
  return api<Project[]>("/projects");
}

export function listRuns(projectId: string, limit = 50): Promise<Run[]> {
  return api<Run[]>(`/projects/${projectId}/runs?limit=${limit}`);
}

export function updateProject(
  projectId: string,
  payload: { name?: string | null; tags?: string[] | null; settings?: ProjectSettings | null }
): Promise<Project> {
  return api<Project>(`/projects/${projectId}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function createProject(payload: { name: string; tags: string[]; settings: ProjectSettings }): Promise<Project> {
  return api<Project>("/projects", { method: "POST", body: JSON.stringify(payload) });
}

export function createRun(
  projectId: string,
  payload: { query_text: string; mode: string; parent_run_id?: string | null; purpose?: string | null }
): Promise<RunIntentResponse> {
  return api<RunIntentResponse>(`/projects/${projectId}/runs`, { method: "POST", body: JSON.stringify(payload) });
}

export function createPlan(runId: string): Promise<PlanStep[]> {
  return api<PlanStep[]>(`/runs/${runId}/plan`, { method: "POST" });
}

export function startRun(runId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/runs/${runId}/start`, { method: "POST" });
}

export function cancelRun(runId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/runs/${runId}/cancel`, { method: "POST" });
}

export function pauseRun(runId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/runs/${runId}/pause`, { method: "POST" });
}

export function resumeRun(runId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/runs/${runId}/resume`, { method: "POST" });
}

export function getSnapshot(runId: string): Promise<Snapshot> {
  return api<Snapshot>(`/runs/${runId}/snapshot`);
}

export function searchMemory(projectId: string, q: string): Promise<MemorySearchResult[]> {
  return api<MemorySearchResult[]>(`/projects/${projectId}/memory/search?q=${encodeURIComponent(q)}`);
}

export function listUserMemory(query = "", tag = "", limit = 50): Promise<UserMemory[]> {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (tag) params.set("tag", tag);
  params.set("limit", String(limit));
  return api<UserMemory[]>(`/memory/list?${params.toString()}`);
}

export function createUserMemory(payload: {
  title?: string | null;
  content: string;
  tags?: string[] | null;
  source?: string | null;
  from?: string | null;
}): Promise<UserMemory> {
  return api<UserMemory>("/memory/create", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteUserMemory(memoryId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/memory/${memoryId}`, { method: "DELETE" });
}

export function pinUserMemory(memoryId: string): Promise<UserMemory> {
  return api<UserMemory>(`/memory/${memoryId}/pin`, { method: "POST" });
}

export function unpinUserMemory(memoryId: string): Promise<UserMemory> {
  return api<UserMemory>(`/memory/${memoryId}/unpin`, { method: "POST" });
}

export function listReminders(status = "", limit = 200): Promise<Reminder[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  return api<Reminder[]>(`/reminders?${params.toString()}`);
}

export function cancelReminder(reminderId: string): Promise<Reminder> {
  return api<Reminder>(`/reminders/${reminderId}`, { method: "DELETE" });
}

export function listApprovals(runId: string): Promise<Approval[]> {
  return api<Approval[]>(`/runs/${runId}/approvals`);
}

export function approve(approvalId: string, decision?: { limit?: number; action?: string }): Promise<Approval> {
  return api<Approval>(`/approvals/${approvalId}/approve`, {
    method: "POST",
    body: JSON.stringify({ decision: decision || null })
  });
}

export function reject(approvalId: string): Promise<Approval> {
  return api<Approval>(`/approvals/${approvalId}/reject`, { method: "POST" });
}

export function resolveConflict(runId: string, conflictId: string): Promise<Run> {
  return api<Run>(`/runs/${runId}/conflicts/${conflictId}/resolve`, { method: "POST" });
}

export function retryTask(runId: string, taskId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/runs/${runId}/tasks/${taskId}/retry`, { method: "POST" });
}

export function retryStep(runId: string, stepId: string): Promise<StatusResponse> {
  return api<StatusResponse>(`/runs/${runId}/steps/${stepId}/retry`, { method: "POST" });
}

export async function downloadArtifact(artifactId: string): Promise<Blob> {
  return apiBlob(`/artifacts/${artifactId}/download`);
}

export async function downloadSnapshot(runId: string): Promise<Blob> {
  return apiBlob(`/runs/${runId}/snapshot/download`);
}

export function storeOpenAIKey(apiKey: string): Promise<OpenAIStoreResponse> {
  return api<OpenAIStoreResponse>("/secrets/openai", { method: "POST", body: JSON.stringify({ api_key: apiKey }) });
}

export function storeOpenAIKeyLocal(apiKey: string): Promise<OpenAIStoreResponse> {
  return api<OpenAIStoreResponse>("/secrets/openai_local", { method: "POST", body: JSON.stringify({ api_key: apiKey }) });
}

export function getLocalOpenAIStatus(): Promise<{ stored: boolean }> {
  return api<{ stored: boolean }>("/secrets/openai_local");
}

export function apiBase() {
  return API_BASE;
}

export function getSessionToken() {
  return sessionToken;
}
