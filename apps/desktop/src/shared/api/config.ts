type EnvMap = Record<string, string | undefined>;
type RuntimeConfig = {
  apiBaseUrl?: string;
  bridgeBaseUrl?: string;
};

const env = ((import.meta as ImportMeta & { env?: EnvMap }).env ?? {}) as EnvMap;
const processEnv = (() => {
  if (typeof globalThis === "undefined") return {} as Record<string, string | undefined>;
  const candidate = globalThis as { process?: { env?: Record<string, string | undefined> } };
  return candidate.process?.env || {};
})();
const runtimeConfig: RuntimeConfig =
  typeof globalThis !== "undefined"
    ? ((globalThis as { __ASTRA_CONFIG__?: RuntimeConfig }).__ASTRA_CONFIG__ ?? {})
    : {};

const mergedEnv: EnvMap = {
  ...processEnv,
  ...env
};

function normalizeBaseUrl(value: string, label: string, requiredPathPrefix?: string): string {
  const trimmed = value.trim();
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error(`Invalid ${label}: ${value}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`Invalid ${label} protocol: ${parsed.protocol}`);
  }
  parsed.hash = "";
  parsed.search = "";
  const normalizedPath = parsed.pathname.replace(/\/+$/, "");
  if (requiredPathPrefix && !normalizedPath.startsWith(requiredPathPrefix)) {
    throw new Error(`Invalid ${label} path: expected prefix ${requiredPathPrefix}, got ${normalizedPath || "/"}`);
  }
  parsed.pathname = normalizedPath;
  return parsed.toString().replace(/\/$/, "");
}

export function resolveApiBaseUrlFromEnv(envMap: EnvMap, runtime: RuntimeConfig = {}): string {
  const candidate = envMap.VITE_ASTRA_API_BASE_URL || runtime.apiBaseUrl;
  if (!candidate) {
    throw new Error("Missing VITE_ASTRA_API_BASE_URL (or window.__ASTRA_CONFIG__.apiBaseUrl)");
  }
  return normalizeBaseUrl(candidate, "VITE_ASTRA_API_BASE_URL", "/api/v1");
}

export function resolveBridgeBaseUrlFromEnv(envMap: EnvMap, runtime: RuntimeConfig = {}): string {
  const candidate = envMap.VITE_ASTRA_BRIDGE_BASE_URL || runtime.bridgeBaseUrl;
  if (!candidate) {
    throw new Error("Missing VITE_ASTRA_BRIDGE_BASE_URL (or window.__ASTRA_CONFIG__.bridgeBaseUrl)");
  }
  return normalizeBaseUrl(candidate, "VITE_ASTRA_BRIDGE_BASE_URL");
}

const API_BASE_URL = resolveApiBaseUrlFromEnv(mergedEnv, runtimeConfig);
const BRIDGE_BASE_URL = resolveBridgeBaseUrlFromEnv(mergedEnv, runtimeConfig);

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function getBridgeBaseUrl(): string {
  return BRIDGE_BASE_URL;
}

export const ASTRA_DATA_DIR = mergedEnv.VITE_ASTRA_DATA_DIR;
export const ASTRA_BASE_DIR = mergedEnv.VITE_ASTRA_BASE_DIR;
