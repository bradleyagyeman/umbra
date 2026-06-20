# Umbra's Biggest Issue: CIS Bot and Risk Detection

## Purpose

This brief explains the central scaling problem in Umbra so another model can
reason about it without needing private repository access.

Umbra is a Python CLI that helps identify newly formed active Virginia LLCs from
the Virginia State Corporation Commission CIS website. The product goal is to
find new LLC owners quickly enough to warn them about misleading third-party
mail solicitations that look official or pressure them into paying for services
that may be unnecessary, free, or available directly from the SCC.

## The Core Problem

The biggest issue is not local code speed. It is CIS bot and risk detection.

Umbra currently depends on Playwright launching local headed Google Chrome and
using the CIS website like a person would. This path works, but CIS commonly
shows a bot or reCAPTCHA-style rejection on the first search submission. A
second attempt in the same headed Chrome session usually succeeds.

That means Umbra can collect data carefully, but cannot safely scale by simply
adding more browser sessions, switching to headless mode, or reducing delays
aggressively. The bottleneck is the website deciding whether the session looks
trustworthy enough to process the search.

## Current Supported Workflow

Umbra's supported path is:

1. Launch local headed Google Chrome through Playwright.
2. Open the CIS business search flow.
3. Search by formation date range.
4. Filter for active Limited Liability Company records only.
5. Export the result CSV from CIS.
6. Normalize and write the final CSV under repo-local `data/`.

Large date ranges are handled through a batch command. The batch command splits
a date range into monthly or weekly chunks, runs the chunks sequentially in one
headed Chrome session, saves per-chunk CSVs, and writes a manifest that lets the
run resume later.

The project intentionally keeps CIS concurrency at 1. That means one active CIS
browser/search lane at a time.

## What Has Already Been Tried

### Headed Chrome

Headed Chrome is the only proven production path. It still often sees the first
submit rejected, but retrying in the same session usually works.

### Headless Chrome

Headless browser automation is considered out of bounds for the current
production path because it is more likely to trigger detection and has not been
the reliable route.

### Persistent Chrome Profiles

A persistent profile experiment was tested. It made first-submit rejection worse
instead of better. The project now uses a fresh ephemeral browser context per
run while reusing the same headed Chrome session across chunks in that run.

### Lower Delay Tuning

Delay tuning is not the main opportunity. Timing data showed that reCAPTCHA or
bot-related submit handling dominates the slow path, not normal local waits.

### Direct Endpoint Replay

Directly replaying CIS export endpoints outside the browser session is
considered brittle and risky. It may save seconds, but it risks server-side
session validation drift and looks less like ordinary browser use.

### Alternative Bulk/Open Data Sources

The current product direction is to ignore alternative bulk/open-data routes for
fresh LLC detection. The project should treat CIS as the source of truth unless
the user explicitly revisits that decision.

## Current Capabilities

Umbra can now do the following:

- Query CIS for active Virginia LLC formations.
- Export normalized CSV files.
- Split large date ranges into sequential chunks.
- Save per-run manifests under `data/runs/<run-id>/`.
- Save per-chunk CSVs under `data/runs/<run-id>/chunks/`.
- Resume an interrupted batch run without repeating succeeded chunks.
- Inspect a saved batch run without opening Chrome.
- Retry failed chunks based on configured attempt limits.
- Keep partial successful work instead of losing an entire long run.

These features make Umbra operationally reliable for careful CIS-backed runs.
They do not eliminate the CIS detection ceiling.

## Why This Blocks Scale

The first-submit bot rejection is the strongest signal that CIS is scoring the
browser/session and sometimes rejecting automation-like behavior. Because of
that, the following scale strategies are risky:

- Running many headed browsers at once.
- Running headless browsers.
- Rotating profiles or browser identities.
- Hammering CIS with high-frequency searches.
- Replaying internal endpoints outside the browser.
- Lowering delays until failures increase.

Those approaches could increase rejection rates, cause inconsistent data, or
make the project harder to operate responsibly.

## The Real Design Question

The question is not how to make Python faster. The real question is:

Can Umbra become reliable enough to collect fresh active LLC data at the cadence
needed to warn owners, while keeping CIS traffic conservative enough that the
browser session continues to be accepted?

## What A Good Solution Should Preserve

Any proposed solution should keep these properties:

- Use headed Google Chrome unless there is strong evidence another route is
  more reliable and acceptable.
- Avoid headless automation as the production path.
- Avoid parallel browser fleets by default.
- Keep searches resumable and observable.
- Classify failures instead of treating every failure as generic.
- Stop or cool down on repeated bot rejection instead of brute-forcing.
- Keep raw per-chunk artifacts for audit and debugging.
- Keep output constrained to repo-local `data/`.
- Avoid relying on stale or non-CIS data for fresh LLC detection.

## Most Useful Next Improvements

The highest-value improvements are likely operational rather than stealthy:

1. Improve failure classification so bot rejection, export timeout, navigation
   timeout, maintenance pages, and schema drift are recorded distinctly.
2. Add adaptive chunk sizing so large-result prompts or export timeouts split
   into smaller chunks automatically.
3. Add run-level reporting with rejection rate, retry count, chunk duration, row
   count, and failure class.
4. Add conservative scheduling guidance for daily or twice-daily recent-window
   runs with overlap and Entity ID dedupe.
5. Consider a very small concurrency canary only after stable baseline metrics,
   with a hard stop if bot rejection increases.

## Success Criteria

A practical solution is successful if Umbra can:

- Run daily recent-LLC searches with low manual intervention.
- Recover cleanly after a failed chunk or browser crash.
- Avoid repeating successful chunks.
- Produce trustworthy active-LLC CSV output.
- Keep the bot-rejection rate stable or lower than the current headed Chrome
  baseline.
- Avoid triggering repeated CIS rejection during normal use.

Massive scraping throughput is not the near-term success criterion. Reliable,
responsible, fresh LLC detection is.

