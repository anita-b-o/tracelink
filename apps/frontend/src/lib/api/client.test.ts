import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./client";

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

  it("rejects malformed successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", {status:200})));
    await expect(apiRequest("/test")).rejects.toMatchObject({kind:"malformed",status:200});
  });
});
