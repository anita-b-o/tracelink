import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiRequest,
  defaultApiTimeoutMs,
  isDemoEnvironment,
  timeoutMessage,
} from "./client";

describe("API client", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("returns successful JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok:true }), { status:200 })));
    await expect(apiRequest<{ok:boolean}>("/test")).resolves.toEqual({ok:true});
  });

  it.each([
    [404,"Not found"],
    [409,"Conflict"],
    [500,"API error 500"],
  ])("surfaces HTTP %i", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:"specific failure"}), {status})));
    await expect(apiRequest("/test")).rejects.toMatchObject({status,kind:"http",message:expect.stringContaining(message) satisfies string});
  });

  it("surfaces FastAPI 422 field details", async () => {
    const body={detail:[{loc:["body","original_query"],msg:"String should have at most 2000 characters"}]};
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {status:422})));
    await expect(apiRequest("/test")).rejects.toMatchObject({status:422,fieldErrors:["original_query: String should have at most 2000 characters"]});
  });

  it("classifies network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(apiRequest("/test")).rejects.toMatchObject({kind:"network",status:null});
  });

  it("aborts timed-out requests", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url:unknown, init?:RequestInit) => new Promise((_resolve,reject) => init?.signal?.addEventListener("abort",()=>reject(new DOMException("aborted","AbortError"))))));
    const pending=apiRequest("/test",{},25).catch(error=>error as ApiError);
    await vi.advanceTimersByTimeAsync(25);
    await expect(pending).resolves.toMatchObject({kind:"timeout",status:null});
  });

  it("uses a longer timeout and explicit cold-start guidance only for demo", () => {
    const demo = { NEXT_PUBLIC_DEMO_MODE: "true" };
    const normal = { NEXT_PUBLIC_DEMO_MODE: "false" };

    expect(isDemoEnvironment(demo)).toBe(true);
    expect(defaultApiTimeoutMs(demo)).toBe(90_000);
    expect(timeoutMessage(90_000, demo)).toContain("free demo API may still be waking up");
    expect(isDemoEnvironment(normal)).toBe(false);
    expect(defaultApiTimeoutMs(normal)).toBe(15_000);
    expect(timeoutMessage(15_000, normal)).not.toContain("free demo");
  });

  it("rejects malformed successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", {status:200})));
    await expect(apiRequest("/test")).rejects.toMatchObject({kind:"malformed",status:200});
  });
});
