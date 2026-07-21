# Production Roadmap

This file tracks product and platform work only. Assignment and submission tasks
belong in the ignored `local/submission/` workspace.

## P0 — Before handling non-redacted production traffic

- [ ] Replace local filesystem artifacts with an encrypted object store and a
  transactional run index.
- [ ] Add tenant-aware authorization, audit logs, retention controls, and deletion
  workflows.
- [ ] Add provider-side data-retention configuration and a documented data
  processing review.
- [ ] Add centralized secret management and remove reliance on local `.env` in
  deployed environments.
- [ ] Add end-to-end observability for stage latency, cost, retry rates, schema
  failures, review volume, and critical-gate outcomes.

## P1 — Reliability and calibration

- [ ] Add a queue-backed worker model with global rate limiting and idempotency
  keys shared across processes.
- [ ] Add an adjudication workflow for second-reviewer disagreements.
- [ ] Version human-label policies and preserve reviewer/audit provenance.
- [ ] Add automated prompt regression gates over frozen development, holdout, and
  audio-validation sets.
- [ ] Add drift monitoring by workflow, source quality, language, and provider
  model version.

## P2 — Productization

- [ ] Add a service API over the canonical models and run lifecycle.
- [ ] Add a reviewer UI backed by the same import/export contracts.
- [ ] Support pluggable storage and model providers without changing call-level
  schemas.
- [ ] Add configurable organization-specific workflows, rubric overlays, and
  safety policies.
- [ ] Add scheduled audits and alerting for confidence, gate recall, and evidence
  validity regressions.
