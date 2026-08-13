import { NextRequest, NextResponse } from "next/server";

import { backendInternalUrl } from "@/lib/backend-url";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 262_144;
const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "cookie", "origin", "user-agent", "x-csrf-token", "x-request-id"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "cache-control", "retry-after", "x-request-id"];

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const backend = backendInternalUrl();
  if (!backend) return NextResponse.json({ detail: "backend unavailable" }, { status: 503 });
  const { path } = await context.params;
  const safePath = path.map((segment) => encodeURIComponent(segment)).join("/");
  const target = new URL(`/api/${safePath}${request.nextUrl.search}`, backend);
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (!headers.has("x-request-id")) headers.set("x-request-id", crypto.randomUUID());

  let body: ArrayBuffer | undefined;
  if (!['GET', 'HEAD'].includes(request.method)) {
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
      return NextResponse.json({ detail: "request body too large" }, { status: 413 });
    }
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return NextResponse.json({ detail: "request body too large" }, { status: 413 });
    }
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      redirect: "manual",
      cache: "no-store",
    });
    const responseHeaders = new Headers();
    for (const name of FORWARDED_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    const cookieHeaders = typeof upstream.headers.getSetCookie === "function"
      ? upstream.headers.getSetCookie()
      : upstream.headers.get("set-cookie") ? [upstream.headers.get("set-cookie")!] : [];
    for (const cookie of cookieHeaders) responseHeaders.append("set-cookie", cookie);
    return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: "backend unavailable" }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
