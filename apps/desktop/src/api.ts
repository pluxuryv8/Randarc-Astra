// EN kept: публичные пути API и заголовки HTTP — контракт интеграции
import { invoke } from "@tauri-apps/api/tauri";

const DEFAULT_PORT = import.meta.env.VITE_API_PORT || "8055";
const API_BASE = import.meta.env.VITE_API_BASE || `http://127.0.0.1:${DEFAULT_PORT}/api/v1`;
const SESSION_KEY = "astra_session_token";
let sessionToken: string | null = null;

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
  const token = Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
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
  return sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {};
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
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
    headers: {
      ...authHeaders()
    }
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return await res.blob();
}

export function listProjects() {
  return api<any[]>("/projects");
}

export function updateProject(projectId: string, payload: { name?: string | null; tags?: string[] | null; settings?: Record<string, any> | null }) {
  return api<any>(`/projects/${projectId}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function createProject(payload: { name: string; tags: string[]; settings: Record<string, any> }) {
  return api<any>("/projects", { method: "POST", body: JSON.stringify(payload) });
}

export function createRun(projectId: string, payload: { query_text: string; mode: string; parent_run_id?: string | null; purpose?: string | null }) {
  return api<any>(`/projects/${projectId}/runs`, { method: "POST", body: JSON.stringify(payload) });
}

export function createPlan(runId: string) {
  return api<any[]>(`/runs/${runId}/plan`, { method: "POST" });
}

export function startRun(runId: string) {
  return api<any>(`/runs/${runId}/start`, { method: "POST" });
}

export function cancelRun(runId: string) {
  return api<any>(`/runs/${runId}/cancel`, { method: "POST" });
}

export function pauseRun(runId: string) {
  return api<any>(`/runs/${runId}/pause`, { method: "POST" });
}

export function resumeRun(runId: string) {
  return api<any>(`/runs/${runId}/resume`, { method: "POST" });
}

export function getSnapshot(runId: string) {
  return api<any>(`/runs/${runId}/snapshot`);
}

export function searchMemory(projectId: string, q: string) {
  return api<any[]>(`/projects/${projectId}/memory/search?q=${encodeURIComponent(q)}`);
}

export function listApprovals(runId: string) {
  return api<any[]>(`/runs/${runId}/approvals`);
}

export function approve(approvalId: string, decision?: { limit?: number; action?: string }) {
  return api<any>(`/approvals/${approvalId}/approve`, {
    method: "POST",
    body: JSON.stringify({ decision: decision || null })
  });
}

export function reject(approvalId: string) {
  return api<any>(`/approvals/${approvalId}/reject`, { method: "POST" });
}

export function resolveConflict(runId: string, conflictId: string) {
  return api<any>(`/runs/${runId}/conflicts/${conflictId}/resolve`, { method: "POST" });
}

export function retryTask(runId: string, taskId: string) {
  return api<any>(`/runs/${runId}/tasks/${taskId}/retry`, { method: "POST" });
}

export function retryStep(runId: string, stepId: string) {
  return api<any>(`/runs/${runId}/steps/${stepId}/retry`, { method: "POST" });
}

export async function downloadArtifact(artifactId: string): Promise<Blob> {
  return apiBlob(`/artifacts/${artifactId}/download`);
}

export async function downloadSnapshot(runId: string): Promise<Blob> {
  return apiBlob(`/runs/${runId}/snapshot/download`);
}

export function storeOpenAIKey(apiKey: string) {
  return api<any>("/secrets/openai", { method: "POST", body: JSON.stringify({ api_key: apiKey }) });
}

export function storeOpenAIKeyLocal(apiKey: string) {
  return api<any>("/secrets/openai_local", { method: "POST", body: JSON.stringify({ api_key: apiKey }) });
}

export function getLocalOpenAIStatus() {
  return api<{ stored: boolean }>("/secrets/openai_local");
}

export function apiBase() {
  return API_BASE;
}

export function getSessionToken() {
  return sessionToken;
}
