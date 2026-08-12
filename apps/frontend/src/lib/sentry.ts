import type { ErrorEvent } from "@sentry/nextjs";

export function scrubSentryEvent(event: ErrorEvent): ErrorEvent {
  event.user = undefined;
  if (event.request) {
    event.request.cookies = undefined;
    event.request.data = undefined;
    event.request.query_string = undefined;
    if (event.request.headers) {
      for (const key of Object.keys(event.request.headers)) {
        if (["authorization", "cookie", "x-csrf-token"].includes(key.toLowerCase())) {
          delete event.request.headers[key];
        }
      }
    }
  }
  return event;
}
