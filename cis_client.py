"""Virginia SCC CIS client.

Uses Playwright to handle CIS's reCAPTCHA v3 gate, then exports
search results as CSV from cis.scc.virginia.gov/EntitySearch.

Form field IDs captured from CIS search page on 2026-04-16.
"""

import csv
import io
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

CIS_BASE = "https://cis.scc.virginia.gov"
CIS_SEARCH_URL = f"{CIS_BASE}/EntitySearch/Index"
CIS_EXPORT_URL = f"{CIS_BASE}/EntitySearch/ExportSearchResults"

# Values from the CIS search logic dropdown (#BEFilingSearch_ddlSearchLogic)
STARTS_WITH = "2"
EXACT_MATCH = "3"
CONTAINS = "7"

# Values from the CIS entity type dropdown (#BEFilingSearch_ddlBusinessEntityType)
LIMITED_LIABILITY_COMPANY = "1"

# Values from the CIS entity status dropdown (#BEFilingSearch_ddlBusinessEntityStatusType)
ACTIVE_STATUS = "2"

MATCH_MAP = {
    "startswith": STARTS_WITH,
    "exact": EXACT_MATCH,
    "contains": CONTAINS,
}

EXPORT_COLUMNS = [
    "Entity ID",
    "Entity Name",
    "Name Type",
    "Entity Type",
    "Principal Office Address",
    "RA Name",
    "Status",
]


class CISError(Exception):
    """Raised when CIS returns an unexpected response."""


class CISClient:
    """Client for querying the Virginia SCC CIS EntitySearch.

    Uses Playwright to drive a real browser, required because CIS
    gates searches behind reCAPTCHA v3 (server-side session validation).
    """

    def __init__(self, delay: float = 2.0, user_agent: str = "", headless: bool = False):
        self.delay = delay
        self.user_agent = user_agent
        self.headless = headless
        self.timing = False
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._retry_count = 0

    def connect(self) -> None:
        """Launch browser, navigate to CIS, and accept cookie consent."""
        if self._page:
            self._go_to_search_page()
            return

        self._log("Connecting to CIS...")

        self._pw = sync_playwright().start()
        try:
            with self._time_phase("launch"):
                context = self._launch_context()
        except PlaywrightError as exc:
            self._pw.stop()
            self._pw = None
            if self._is_missing_chrome_error(exc):
                raise CISError(
                    'Google Chrome is required because umbra launches '
                    'Playwright with channel="chrome". Install Chrome and '
                    "try again."
                ) from exc
            raise

        self._context = context
        self._page = context.new_page()

        # Mask automation flags so reCAPTCHA v3 scores us as human
        self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        with self._time_phase("cookie/search page"):
            # First visit hits cookie consent gate
            self._page.goto(CIS_SEARCH_URL, wait_until="networkidle")
            self._check_maintenance()

            # Accept cookie consent (always present on fresh browser context)
            accept_btn = self._page.locator("#acceptCookies")
            if accept_btn.is_visible():
                accept_btn.click()
                self._page.wait_for_load_state("networkidle")

            # Navigate to the actual search page
            self._go_to_search_page()
        self._log("Connected.")

    def search_by_name(self, name: str, match_type: str = EXACT_MATCH) -> list[dict]:
        """Search for entities by business name."""
        self._page.select_option("#BEFilingSearch_ddlSearchLogic", value=match_type)
        self._page.fill("#BusinessSearch_Index_txtBusinessName", name)
        self._submit_search()
        return self._get_csv_export()

    def search_by_id(self, entity_id: str) -> list[dict]:
        """Look up a specific entity by its SCC entity ID."""
        self._page.fill("#BusinessSearch_Index_txtBusinessID", str(entity_id))
        self._submit_search()
        return self._get_csv_export()

    def search_by_date_range(
        self, date_from: datetime, date_to: datetime, fetch: bool = True
    ) -> list[dict]:
        """Find entities formed within a date range."""
        with self._time_phase("form fill"):
            # Expand the Advanced Search panel (date fields are hidden by default)
            self._page.click("#AdhvanceClk a")
            self._page.locator("#BEFilingSearch_txtFilingDateFrom").wait_for(
                state="visible"
            )
            self._page.select_option(
                "#BEFilingSearch_ddlBusinessEntityType",
                value=LIMITED_LIABILITY_COMPANY,
            )
            self._page.select_option(
                "#BEFilingSearch_ddlBusinessEntityStatusType",
                value=ACTIVE_STATUS,
            )

            # Set dates via jQuery — Playwright's fill() doesn't trigger
            # the CIS date input mask (dateFromMask/dateToMask) correctly.
            self._page.evaluate(
                f"$('#BEFilingSearch_txtFilingDateFrom').val('{date_from.strftime('%m/%d/%Y')}')"
            )
            self._page.evaluate(
                f"$('#BEFilingSearch_txtFilingDateTo').val('{date_to.strftime('%m/%d/%Y')}')"
            )
        with self._time_phase("submit/reCAPTCHA"):
            self._submit_search()
        if not fetch:
            return []
        return self._get_csv_export()

    def close(self) -> None:
        """Shut down the browser."""
        if self._page:
            self._page = None
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    def save_csv_export(self, path: str | Path) -> tuple[str, int]:
        """Fetch CSV export and write it directly to a file."""
        csv_text = self._fetch_csv_export_text()
        with self._time_phase("normalize/write"):
            clean_csv_text = self._render_clean_csv_export(csv_text)
            filepath = Path(path)
            filepath.write_text(clean_csv_text, encoding="utf-8")
            row_count = self._count_csv_rows(clean_csv_text)
        return str(filepath), row_count

    # -- internal -----------------------------------------------------------

    def _launch_context(self):
        """Launch Chrome and return a browser context."""
        context_opts = {}
        if self.user_agent:
            context_opts["user_agent"] = self.user_agent

        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self._browser.new_context(**context_opts)

    def _submit_search(self, max_retries: int = 3) -> None:
        """Click search, wait for reCAPTCHA v3 and form submission.

        reCAPTCHA v3 scores can be low on fresh browser sessions. If the
        "You may be a bot" dialog appears, we dismiss it and retry — the
        score typically improves as the session ages.
        """
        for attempt in range(1, max_retries + 1):
            try:
                self._retry_count = attempt - 1
                with self._page.expect_navigation(
                    wait_until="networkidle", timeout=60000
                ):
                    self._page.click("#btnSearch")
                break  # navigation happened — search was accepted
            except PlaywrightTimeout:
                # No navigation — check if reCAPTCHA rejected us
                bot_alert = self._page.locator("div.sweet-alert")
                if bot_alert.is_visible() and "bot" in bot_alert.inner_text().lower():
                    bot_alert.locator("button.confirm").click()
                    if attempt < max_retries:
                        self._retry_count = attempt
                        self._log(
                            f"reCAPTCHA rejected (attempt {attempt}/{max_retries}), retrying..."
                        )
                        self._sleep()
                        continue
                    raise CISError(
                        "reCAPTCHA rejected the request after multiple attempts."
                    )
                raise CISError("Search timed out waiting for results.")

        # Handle the >500 results confirmation dialog
        confirm_btn = self._page.locator("div.sweet-alert button.confirm")
        if confirm_btn.is_visible(timeout=1000):
            with self._page.expect_navigation(
                wait_until="networkidle", timeout=30000
            ):
                confirm_btn.click()
        self._timing_log(f"retries: {self._retry_count}")

    def _get_csv_export(self) -> list[dict]:
        """Fetch CSV export using the browser's authenticated session."""
        csv_text = self._fetch_csv_export_text()
        with self._time_phase("normalize"):
            return self._clean_csv_export(csv_text)

    def _fetch_csv_export_text(self) -> str:
        """Return raw CSV export text for the current search results."""
        with self._time_phase("export"):
            self._sleep()
            resp = self._page.context.request.get(
                CIS_EXPORT_URL, params={"hgridex": "5"}, timeout=60000
            )
            csv_text = resp.text()
            self._validate_csv_export_text(csv_text)
        return csv_text

    def _go_to_search_page(self) -> None:
        """Navigate to the CIS search page in the current browser session."""
        self._sleep()
        self._page.goto(CIS_SEARCH_URL, wait_until="networkidle")
        self._check_maintenance()

    @staticmethod
    def _validate_csv_export_text(csv_text: str) -> None:
        """Validate that the export response looks like CSV data."""
        if "Entity ID" not in csv_text[:200]:
            raise CISError("CSV export did not return expected data.")

    @staticmethod
    def _count_csv_rows(csv_text: str) -> int:
        """Count data rows in the exported CSV text."""
        return max(sum(1 for _ in csv.DictReader(io.StringIO(csv_text))), 0)

    @staticmethod
    def _clean_csv_export(csv_text: str) -> list[dict]:
        """Return one normalized result row per entity ID.

        CIS exports can include an unnamed trailing column and multiple name
        records for the same entity. Legal names are the most useful row when
        duplicate entity IDs appear.
        """
        rows = csv.DictReader(io.StringIO(csv_text))
        cleaned_by_id: dict[str, dict] = {}
        fallback_rows: list[dict] = []

        for row in rows:
            cleaned = {
                column: (row.get(column) or "").strip()
                for column in EXPORT_COLUMNS
            }
            entity_id = cleaned["Entity ID"]
            if not entity_id:
                fallback_rows.append(cleaned)
                continue

            previous = cleaned_by_id.get(entity_id)
            if previous is None or (
                previous["Name Type"] != "Legal Name"
                and cleaned["Name Type"] == "Legal Name"
            ):
                cleaned_by_id[entity_id] = cleaned

        return [*cleaned_by_id.values(), *fallback_rows]

    @staticmethod
    def _render_clean_csv_export(csv_text: str) -> str:
        """Render a cleaned CIS export as CSV."""
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(CISClient._clean_csv_export(csv_text))
        return out.getvalue()

    def _check_maintenance(self) -> None:
        """Raise if CIS is showing its maintenance page."""
        if "temporarily unavailable" in (self._page.content()[:500]):
            raise CISError("CIS is temporarily unavailable. Try again later.")

    def _sleep(self) -> None:
        """Throttle follow-up requests when configured."""
        if self.delay > 0:
            time.sleep(self.delay)

    @staticmethod
    def _is_missing_chrome_error(exc: PlaywrightError) -> bool:
        """Detect Playwright launch failures caused by a missing Chrome binary."""
        message = str(exc).lower()
        return (
            "distribution 'chrome' is not found" in message
            or (
                "chrome" in message
                and ("executable doesn't exist" in message or "not found" in message)
            )
        )

    @staticmethod
    def _log(msg: str) -> None:
        """Write diagnostic output to stderr."""
        print(msg, file=sys.stderr)

    @contextmanager
    def _time_phase(self, name: str):
        """Measure a runtime phase when timing output is enabled."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self._timing_log(f"{name}: {time.perf_counter() - started:.2f}s")

    def _timing_log(self, msg: str) -> None:
        """Write timing output to stderr when enabled."""
        if self.timing:
            print(f"[timing] {msg}", file=sys.stderr)
