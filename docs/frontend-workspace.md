# Investigation workspace

Phase 7 turns the existing FastAPI workflow into a desktop-first investigation product. The UI is
English, evidence-first, and uses the Next.js App Router. `/` is the paginated dashboard,
`/investigations/new` creates a case, and `/investigations/[id]?tab=...` owns the workspace.
`/investigations` redirects to `/`.

## Frontend structure

- `app/` contains routes, the root layout, and global Tailwind-compatible CSS.
- `components/ui/` contains accessible status, progress, async-state, and drawer primitives.
- `features/` groups investigations, workspace tables, graph, timeline, Ask, reports, and review.
- `lib/api/` contains the generated OpenAPI declarations, central types, and the only HTTP client.

TanStack Query supplies request deduplication, cache invalidation after actions/reviews, report
polling, and investigation polling. There is no global store. Shareable filters and selected
drawers use URL query parameters; transient form and dialog state remains local.

The API client reads `NEXT_PUBLIC_API_BASE_URL`, aborts after 15 seconds, and distinguishes
network, timeout, malformed response, 404, 409, 422 field validation, and 5xx errors. Regenerate
the versioned declarations while FastAPI is running with `npm run generate:api`.

## Workspace behavior

The header exposes Start only for DRAFT and Cancel only for DRAFT, PENDING, or RUNNING.
Investigation and task data poll every three seconds only while PENDING/RUNNING. Report detail
polls while PENDING/RUNNING and stops for COMPLETED/FAILED. Tabs are URL-addressable and render
one feature at a time.

Lists request 26 rows for a 25-row page, or bounded pages of at most 100 for timeline assembly.
Entities, relationships, sources, documents, and review candidates are filtered server-side.
Document content is loaded on demand as plain text and limited to 5,000 characters. External
links use `target="_blank" rel="noopener noreferrer"`; document and LLM text is never inserted as
HTML.

Timeline events combine materialized relationship starts/ends, accepted claims, contradictions,
and source publication dates. `YYYY`, `YYYY-MM`, and `YYYY-MM-DD` remain unchanged. Sorting compares
year/month/day, then precision, event priority, and stable ID; no missing month/day is invented.

Drawers use dialog semantics, focus the close button, close with Escape, and restore prior focus.
Every feature exposes loading, empty, error, and retry states. Tables collapse secondary columns on
small screens; the mobile graph warns that table views provide the complete experience.

## Testing

Vitest and Testing Library cover the API client, status/progress/actions, entities and mentions,
relationship contradictions/evidence, citations/abstention, reports, review mutations, graph
mapping, and partial-date ordering.

`compose.e2e.yaml` overlays the normal stack with isolated ports/database, offline fake providers,
and the idempotent `python -m tracelink.e2e_seed` fixture. From an empty E2E volume:

```bash
FRONTEND_PORT=3100 BACKEND_PORT=8100 POSTGRES_PORT=55432 REDIS_PORT=56379 \
POSTGRES_DB=tracelink_e2e POSTGRES_PASSWORD=tracelink_e2e \
docker compose -p tracelink-e2e -f compose.yaml -f compose.e2e.yaml \
  up --build -d postgres redis backend worker frontend
docker compose -p tracelink-e2e -f compose.yaml -f compose.e2e.yaml run --rm e2e-fixtures
cd apps/frontend && PLAYWRIGHT_BASE_URL=http://localhost:3100 npm run test:e2e
```

The three serial specs cover the complete workspace journey, candidate review, and graph
interaction. They never contact the public Internet.
