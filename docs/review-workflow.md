# Human review workflow

Review is deliberately candidate-scoped. Phase 7 does not expose arbitrary entity merge or graph
editing. The Review tab defaults to PENDING and combines entity-resolution and relationship
candidates; accepted, rejected, automatic, and contradicted states remain inspectable by filter.

## Entity resolution

`POST /api/entity-resolution-candidates/{id}/accept` locks the candidate, mention, provisional
entity, and target. The service requires PENDING, matching entity types, and a provisional source.
It moves mentions and non-duplicate aliases to the target, reconciles dependent relationship
candidates and materialized relationships, moves Evidence before removing duplicate or collapsed
self-referential edges, and marks the provisional metadata with `resolution_merged_into` and a
timestamp. Provenance records are retained.

Reject marks only the candidate REJECTED and sets `reviewed_at`; it does not delete evidence or
either entity. Other PENDING candidates for an accepted mention are rejected in the same
transaction.

## Relationship candidates

Accept revalidates exact offsets, investigation ownership, endpoint compatibility, and
self-reference on the backend. AFFIRMS materializes CONFIRMED plus Supporting Evidence. NEGATES
preserves the opposing position as a CONTRADICTED relationship plus Contradicting Evidence. ENDS
keeps the historical relationship, sets its end, and writes Temporal Evidence. Reject changes only
candidate status and audit time.

The same final decision is idempotent. Reversing ACCEPTED/REJECTED or reviewing automatic states
returns 409; missing IDs return 404. Every decision commits atomically and `RelationshipCandidate`
audit time is introduced by migration `0007_workspace_review`.

Future re-review would require an explicit append-only decision/audit model. Phase 7 intentionally
does not mutate a final human decision in place.
