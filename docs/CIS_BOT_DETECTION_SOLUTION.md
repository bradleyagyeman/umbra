# CIS Bot Detection: Proposed Solution

## Purpose

This report answers the design question raised in
`docs/CIS_BOT_DETECTION_ISSUE.md`: can Umbra collect fresh active Virginia LLC
data at the cadence needed to warn owners, while keeping CIS traffic
conservative enough that the browser session continues to be accepted?

The recommendation is grounded in the current code (`umbra.py`,
`batch_runner.py`) and the benchmarks recorded in `PROJECT_STATE.md`.

## The Reframe

Umbra does not need to beat the detector. It needs to shrink the job until the
detector no longer matters.

The product goal is to warn new LLC owners quickly. That requires freshness,
not throughput. The project's own benchmark shows a 7-day window returning
roughly 3,000 rows in one search within one headed session (76s with one
retry, then 13.7s with zero retries on repeat). A daily run over a trailing
window is therefore one or two CIS searches per day — far below any plausible
detection threshold.

Scale pressure only exists for historical backfill, which is a one-time task
and is allowed to be slow.

Stealth approaches (headless mode, fingerprint manipulation, browser fleets,
endpoint replay) remain ruled out. They are both riskier and unnecessary once
the steady-state workload is this small.

## Evidence Read From Current Behavior

The observed pattern — first submit rejected, second submit in the same
session succeeds, and persistent profiles made rejection worse — is the
classic signature of a risk score that starts low for a fresh session and
rises after real interaction. This is not a fault to eliminate; it is a fixed
cost to budget for. Because batch chunks share one headed Chrome session, only
the first chunk pays it.

## Recommended Changes

### 1. Daily fresh-window cadence with a dedupe ledger (the product solve)

Add a daily recipe (command or documented schedule):

- Each day, query a trailing 3-day window. The overlap absorbs CIS indexing
  lag and missed days.
- Dedupe results against a persistent cross-run ledger of seen Entity IDs
  stored under repo-local `data/`.
- Emit only the LLCs not previously seen — the actual warning deliverable.

`merge_entity_rows` in `batch_runner.py` already dedupes by Entity ID within a
run; the missing piece is the persistent ledger across runs. This change
delivers the warning use-case with about one search per day, permanently
inside the proven headed-Chrome path.

### 2. Formalize the first-submit rejection as session warm-up

- Treat the first `BOT_REJECTED` per browser session as expected. Either fire
  a deliberate cheap warm-up search at session start before the first chunk,
  or exempt a session-initial rejection from the chunk's `--max-attempts`
  budget (the retry loop in `umbra.py`, around lines 290–327).
- Record session warm-up rejections separately from genuine chunk failures in
  the manifest so metrics are not polluted by an already-explained artifact.

### 3. Circuit breaker with cooldown on repeated rejection

Failure classification already exists (`classify_failure` in
`batch_runner.py`). The missing piece is the response policy:

- Second consecutive `BOT_REJECTED` in a session: cool down (for example 60
  seconds, then 5 minutes) before retrying.
- Third consecutive: stop the run cleanly, persist manifest state, and tell
  the operator to resume later with `--resume`. Never brute-force.

This converts a rising rejection rate from a data-quality hazard into a clean,
resumable stop.

### 4. Run-level reporting before any ambition

Add a `--report` view to the run inspector: rejection rate, retry counts,
per-chunk duration (manifests already store `started_at` and `finished_at`),
row counts, and a failure-class histogram.

This provides the stable baseline that the issue brief requires before any
concurrency canary. Once the daily cadence exists, the canary is likely never
needed — there is nothing left to parallelize.

### 5. Adaptive chunk splitting (backfill only)

On `EXPORT_TIMEOUT` or large-result prompts, split the chunk in half and
insert the sub-chunks into the manifest. Useful, but it only matters for
one-time backfill, so it is last in priority.

## What Not To Do

Unchanged from the issue brief, and reaffirmed here:

- No headless automation as the production path.
- No parallel browser fleets.
- No profile or identity rotation.
- No direct endpoint replay outside the browser.
- No delay-lowering until failures increase.

These are not only detection risks; they conflict with operating the project
responsibly.

## The One Structural Alternative

The only true removal of the detection ceiling is an official channel, such as
an SCC bulk data subscription. The project has explicitly parked that
decision, so it is flagged here as the single structural alternative — not a
recommendation to revisit it now.

## Priority Order

1. Daily fresh-window cadence plus persistent Entity ID dedupe ledger.
2. Session warm-up handling for the first-submit rejection.
3. Circuit breaker with cooldown and clean resumable stop.
4. Run-level reporting (`--report`).
5. Adaptive chunk splitting for backfill.

## Mapping To Success Criteria

| Success criterion (from issue brief)        | Addressed by |
| -------------------------------------------- | ------------ |
| Daily recent-LLC searches, low intervention   | Change 1     |
| Clean recovery after failed chunk or crash    | Changes 3, 5 (existing resume) |
| No repeating successful chunks                | Existing manifests + Change 1 ledger |
| Trustworthy active-LLC CSV output             | Change 1 (ledger-deduped output) |
| Stable or lower bot-rejection rate            | Changes 2, 3, 4 |
| No repeated CIS rejection in normal use       | Changes 2, 3 |

Massive throughput remains a non-goal. Reliable, responsible, fresh LLC
detection is achievable with the changes above, entirely within the supported
headed-Chrome path.
