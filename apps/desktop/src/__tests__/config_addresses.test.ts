/// <reference types="node" />
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolveApiBaseUrlFromEnv, resolveBridgeBaseUrlFromEnv } from "../shared/api/config";

describe("address config", () => {
  it("test_desktop_config_resolves_base_url", () => {
    const resolved = resolveApiBaseUrlFromEnv({
      VITE_ASTRA_API_BASE_URL: "http://127.0.0.1:18055/api/v1/"
    });
    assert.equal(resolved, "http://127.0.0.1:18055/api/v1");
  });

  it("requires explicit VITE_ASTRA_API_BASE_URL", () => {
    assert.throws(() => resolveApiBaseUrlFromEnv({}), /Missing VITE_ASTRA_API_BASE_URL/);
  });

  it("test_desktop_config_resolves_bridge_url", () => {
    const resolved = resolveBridgeBaseUrlFromEnv({
      VITE_ASTRA_BRIDGE_BASE_URL: "http://127.0.0.1:43124/"
    });
    assert.equal(resolved, "http://127.0.0.1:43124");
  });
});
