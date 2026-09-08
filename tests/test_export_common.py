"""fetch_all pagination, stable order, and retry behavior."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from export_common import PAGE_SIZE, fetch_all, require_service_role_key  # noqa: E402


def _resp(status, payload, headers=None):
    r = Mock()
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    else:
        r.raise_for_status.return_value = None
    return r


def test_fetch_all_sends_stable_order_and_paginates():
    page1 = [{"id": i} for i in range(PAGE_SIZE)]
    page2 = [{"id": PAGE_SIZE}]
    with patch(
        "export_common.requests.get", side_effect=[_resp(200, page1), _resp(200, page2)]
    ) as get:
        rows = fetch_all("https://example.supabase.co", "key", "inventory", "id")
    assert len(rows) == PAGE_SIZE + 1
    assert get.call_count == 2
    first_params = get.call_args_list[0].kwargs["params"]
    assert first_params["order"] == "id.asc"
    assert first_params["limit"] == PAGE_SIZE
    assert first_params["offset"] == 0
    assert get.call_args_list[1].kwargs["params"]["offset"] == PAGE_SIZE


def test_fetch_all_retries_502_then_succeeds():
    with patch("export_common.time.sleep"):
        with patch(
            "export_common.requests.get",
            side_effect=[_resp(502, {"err": "bad"}), _resp(200, [{"id": 1}])],
        ) as get:
            rows = fetch_all("https://example.supabase.co", "key", "profiles", "id")
    assert rows == [{"id": 1}]
    assert get.call_count == 2


def test_fetch_all_does_not_retry_400():
    with patch("export_common.requests.get", return_value=_resp(400, {"err": "bad"})) as get:
        with pytest.raises(requests.HTTPError):
            fetch_all("https://example.supabase.co", "key", "profiles", "id")
    assert get.call_count == 1


def test_fetch_all_retries_timeout():
    with patch("export_common.time.sleep"):
        with patch(
            "export_common.requests.get",
            side_effect=[requests.Timeout("t"), _resp(200, [])],
        ) as get:
            rows = fetch_all("https://example.supabase.co", "key", "profiles", "id")
    assert rows == []
    assert get.call_count == 2


def test_require_service_role_key_strips(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "  abc  ")
    assert require_service_role_key() == "abc"


def test_require_service_role_key_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(SystemExit):
        require_service_role_key()
