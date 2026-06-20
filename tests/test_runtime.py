from unittest.mock import Mock
from datetime import datetime

from playwright.sync_api import Error as PlaywrightError

from cis_client import ACTIVE_STATUS, LIMITED_LIABILITY_COMPANY, CISClient, CISError


def test_sleep_uses_configured_delay(monkeypatch) -> None:
    client = CISClient(delay=1.5)
    sleep_mock = Mock()
    monkeypatch.setattr("cis_client.time.sleep", sleep_mock)

    client._sleep()

    sleep_mock.assert_called_once_with(1.5)


def test_sleep_skips_non_positive_delay(monkeypatch) -> None:
    client = CISClient(delay=0)
    sleep_mock = Mock()
    monkeypatch.setattr("cis_client.time.sleep", sleep_mock)

    client._sleep()

    sleep_mock.assert_not_called()


def test_connect_reports_missing_chrome(monkeypatch) -> None:
    client = CISClient()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self
            self.stopped = False

        def launch(self, **kwargs):
            raise PlaywrightError("Chromium distribution 'chrome' is not found")

        def stop(self) -> None:
            self.stopped = True

    fake_pw = FakePlaywright()

    class FakeManager:
        def start(self):
            return fake_pw

    monkeypatch.setattr("cis_client.sync_playwright", lambda: FakeManager())

    try:
        client.connect()
    except CISError as exc:
        assert "Google Chrome is required" in str(exc)
    else:
        raise AssertionError("Expected CISError for missing Chrome")

    assert fake_pw.stopped is True


def test_date_range_query_filters_to_active_llcs() -> None:
    client = CISClient(delay=0)
    calls = []

    class FakeLocator:
        def wait_for(self, state):
            calls.append(("wait_for", state))

    class FakePage:
        def click(self, selector):
            calls.append(("click", selector))

        def locator(self, selector):
            calls.append(("locator", selector))
            return FakeLocator()

        def select_option(self, selector, value):
            calls.append(("select_option", selector, value))

        def evaluate(self, script):
            calls.append(("evaluate", script))

    client._page = FakePage()
    client._submit_search = lambda: calls.append(("submit",))
    client._get_csv_export = lambda: []

    client.search_by_date_range(datetime(2026, 5, 22), datetime(2026, 5, 29))

    assert (
        "select_option",
        "#BEFilingSearch_ddlBusinessEntityType",
        LIMITED_LIABILITY_COMPANY,
    ) in calls
    assert (
        "select_option",
        "#BEFilingSearch_ddlBusinessEntityStatusType",
        ACTIVE_STATUS,
    ) in calls


def test_clean_csv_export_drops_extra_column_and_dedupes_entity_ids() -> None:
    csv_text = (
        "Entity ID,Entity Name,Name Type,Entity Type,Principal Office Address,"
        "RA Name,Status,\n"
        "12022368,1 Source Title and Escrow,Reserved Name,"
        'Limited Liability Company,"147 Veterans Pkwy, Murfreesboro, TN",'
        "Northwest Registered Agent LLC,Active,\n"
        '12022368,"1 Source Title and Escrow, LLC",Legal Name,'
        'Limited Liability Company,"147 Veterans Pkwy, Murfreesboro, TN",'
        "Northwest Registered Agent LLC,Active,\n"
    )

    cleaned = CISClient._clean_csv_export(csv_text)

    assert cleaned == [
        {
            "Entity ID": "12022368",
            "Entity Name": "1 Source Title and Escrow, LLC",
            "Name Type": "Legal Name",
            "Entity Type": "Limited Liability Company",
            "Principal Office Address": "147 Veterans Pkwy, Murfreesboro, TN",
            "RA Name": "Northwest Registered Agent LLC",
            "Status": "Active",
        }
    ]


def test_render_clean_csv_export_writes_documented_columns_only() -> None:
    csv_text = (
        "Entity ID,Entity Name,Name Type,Entity Type,Principal Office Address,"
        "RA Name,Status,\n"
        "1,Acme LLC,Legal Name,Limited Liability Company,Somewhere,Agent,Active,\n"
    )

    rendered = CISClient._render_clean_csv_export(csv_text)

    assert rendered == (
        "Entity ID,Entity Name,Name Type,Entity Type,"
        "Principal Office Address,RA Name,Status\r\n"
        "1,Acme LLC,Legal Name,Limited Liability Company,Somewhere,Agent,Active\r\n"
    )
