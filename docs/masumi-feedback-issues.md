# Masumi Feedback Issues (Preprod)

Date: 2026-02-28  
Project: `masumi-agents` / `aikido-reviewer`

## 1) Single fixed pricing per agent listing

- Observation: Registry pricing model for one listing is fixed (`AgentPricing.pricingType = "Fixed"`).
- Impact: Cannot offer multiple paid tiers (for example quick/standard/deep) under one `agentIdentifier`.
- Improvement request: Support multi-tier pricing on a single listing, with per-tier metadata and selected tier passed into payment request.

## 2) No in-place price update flow for existing listing

- Observation: Changing price required creating a new registration entry and switching to a new `agentIdentifier`, then deregistering the old one.
- Impact: Operational overhead, possible client drift to old IDs, and extra on-chain transitions for simple pricing changes.
- Improvement request: Add safe in-place update semantics (for example `PATCH` price for active listing) or versioned updates linked to one stable canonical agent ID.

## 3) Registry listing UX includes stale/failed entries

- Observation: Registry response includes `RegistrationFailed` and deregistered history entries alongside active ones.
- Impact: Clients/integrations can accidentally select non-active or outdated entries.
- Improvement request: Add first-class filtering/sorting for active listings, and provide a canonical "current active registration" query by agent name/apiBaseUrl.

## 4) Price unit clarity (USDM amount encoding)

- Observation: Price amounts are encoded as integer strings (for example `4990000` for `4.99 USDM`).
- Impact: Easy to misconfigure by orders of magnitude when updating pricing manually.
- Improvement request: Accept a human-readable decimal field in API and/or return explicit metadata (decimals, display amount, normalized amount).

## 5) State transition observability

- Observation: Registration/deregistration transitions are asynchronous and can remain in intermediate states (`Requested`, `Initiated`) for some time.
- Impact: Harder to automate deployment orchestration without polling loops.
- Improvement request: Add webhook/event stream support for registry and payment state transitions, plus stronger transition SLAs.

## 6) Signed timing fields for purchase are under-documented

- Observation: Creating `/purchase/` requires timing fields that must match the signed `blockchainIdentifier` payload. In practice, using a manually generated `payByTime` caused rejections.
- Observed behavior:
  - `payByTime` not matching signed values can fail with `Invalid blockchain identifier, signature invalid`.
  - Other invalid timing values can fail with `Pay by time must be in the future (max. 5 minutes)`.
- Impact: Integrators can build valid-looking payloads that still fail, especially when connecting directly from MIP-003 agent outputs.
- Improvement request:
  - In docs, make explicit that clients should resolve timing fields from payment service (`/payment/resolve-blockchain-identifier`) and reuse exact values for purchase.
  - Add an example E2E sequence with required field provenance for each step.

## 7) MIP-003 handoff fields are not enough for direct purchase call

- Observation: Agent `start_job` responses include `submitResultTime`, `unlockTime`, `externalDisputeUnlockTime`, `inputHash`, etc., but not the `payByTime` we needed for reliable purchase submission.
- Impact: Buyers/integrators have to discover additional hidden step(s) and reverse-engineer which fields are canonical.
- Improvement request:
  - Either include canonical `payByTime` in start response contracts, or document that buyer must call resolve endpoint before `/purchase/`.

## 8) Asset unit format ambiguity (`USDM` symbol vs full asset unit hex)

- Observation: Pricing/paid funds using symbol-like unit values (`USDM`) led to batching/runtime failures in our flow; using full asset unit hex resolved it.
- Impact: Silent or late-stage failures in payment batching; difficult to diagnose from client side.
- Improvement request:
  - Standardize docs and API validation around accepted token unit format.
  - Reject ambiguous/non-canonical unit formats early with precise validation error.

## 9) Error reporting quality on critical purchase path

- Observation: Several failures returned generic errors (`500 Internal Server Error`, sparse outer error context), while the real issue was field format/signature/timing mismatch.
- Impact: Extended debugging cycles and false assumptions (wallet funding, network health) before real cause is visible.
- Improvement request:
  - Return structured, user-actionable error payloads on `/purchase/` and batching internals.
  - Include field-level error diagnostics (which field mismatched signed payload).

## 10) Local template success does not guarantee hosted parity

- Observation: Local setup worked with template defaults, but Railway surfaced additional integration constraints (timing/signature correctness, token unit strictness, provider limits).
- Impact: Teams can pass local checks and still fail in hosted E2E when they switch environments.
- Improvement request:
  - Ship an official hosted E2E checklist/smoke script that validates full buyer->purchase->lock->callback->result flow.
  - Add explicit guidance for provider quota failures (`Blockfrost 402`), expected symptoms, and remediation.

## 11) Docs/template version drift risk

- Observation: This project used `masumi==0.1.39`, while newer package versions exist; docs/examples across guides/API references can diverge in behavior expectations.
- Impact: Integrators may follow examples that are valid for one version set but fail for another.
- Improvement request:
  - Publish compatibility matrix (SDK version <-> payment service version <-> docs section).
  - Version-pin docs examples and label legacy flows clearly.

## Railway E2E timeline notes (this project)

- 2026-02-27: Core paid-flow migration completed; standalone local bypass removed.
- 2026-02-28: Hosted E2E repeatedly stalled/failed until:
  - canonical token unit format was corrected,
  - purchase request reused signed timing values from resolve endpoint,
  - provider limit/transient errors were ruled out.
- 2026-02-28 (final): Full live E2E succeeded end-to-end (`start_job` -> `/purchase/` -> funds lock -> callback -> completed report).

## Notes from this project run

- Final chosen model: one plan only, deep analysis, `4.99 USDM` (`4990000`).
- Active `agentIdentifier` was rotated to new registration and old one was deregistered.
- This file is intended as a handoff checklist for final feedback to Masumi team.
