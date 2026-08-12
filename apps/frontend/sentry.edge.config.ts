import * as Sentry from "@sentry/nextjs";

import { scrubSentryEvent } from "./src/lib/sentry";

const dsn = process.env.SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.APP_ENV,
    sendDefaultPii: false,
    tracesSampleRate: Number(process.env.SENTRY_TRACES_SAMPLE_RATE ?? "0"),
    beforeSend: scrubSentryEvent,
  });
}

