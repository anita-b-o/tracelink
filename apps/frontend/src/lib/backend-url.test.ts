import { describe, expect, it } from "vitest";

import { backendInternalUrl } from "./backend-url";

describe("backendInternalUrl", () => {
  it("preserves an explicitly configured URL", () => {
    expect(
      backendInternalUrl({
        BACKEND_INTERNAL_URL: "https://api.example.test/base",
        BACKEND_INTERNAL_HOSTPORT: "tracelink-api-ab12:8000",
      }),
    ).toBe("https://api.example.test/base");
  });

  it("builds an HTTP URL from Render's internal hostport", () => {
    expect(
      backendInternalUrl({
        BACKEND_INTERNAL_URL: undefined,
        BACKEND_INTERNAL_HOSTPORT: "tracelink-api-ab12:8000",
      }),
    ).toBe("http://tracelink-api-ab12:8000");
  });

  it("returns null when neither setting is available", () => {
    expect(
      backendInternalUrl({
        BACKEND_INTERNAL_URL: undefined,
        BACKEND_INTERNAL_HOSTPORT: undefined,
      }),
    ).toBeNull();
  });
});
