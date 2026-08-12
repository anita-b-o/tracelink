# Release checklist

- [ ] Ruff format/check, mypy strict y pytest completos verdes.
- [ ] Alembic base→head, downgrade/upgrade y `alembic check` verdes.
- [ ] ESLint, TypeScript, Vitest, OpenAPI y Next production build verdes.
- [ ] Playwright auth/workspace/cross-user verde con worker/outbox reales.
- [ ] `pip-audit`, `npm audit`, Bandit y gitleaks revisados.
- [ ] Imágenes production y Compose staging construyen/validan sin bind mounts.
- [ ] `APP_ENV`, CORS, hosts, registro, providers, cookies y secretos revisados.
- [ ] Backup custom-format creado; checksum y restore smoke verificados.
- [ ] Migración asignada exclusivamente al pre-deploy del backend.
- [ ] Readiness, worker ping, outbox health y métricas verificados.
- [ ] Smoke autenticado y aislamiento cross-user ejecutados en staging.
- [ ] Dashboard/detail/graph/search/Ask/report enqueue comparados con baseline.
- [ ] Responsable y procedimiento de rollback confirmados.
- [ ] Staging aprobado antes de production; production requiere autorización separada.

