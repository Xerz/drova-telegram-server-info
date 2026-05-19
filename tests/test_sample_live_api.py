from __future__ import annotations

from typing import Any

import pytest

from scripts import sample_live_api
from scripts.sample_live_api import DrovaSampler, Sanitizer


def test_sampler_next_iteration_read_endpoints_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = DrovaSampler(
        {
            "DROVA_PROXY_TOKEN": "token",
            "TEST_STATION_UUID": "station-1",
            "TEST_PRODUCT_UUID": "product-1",
        }
    )
    calls: list[tuple[str, str, str, dict[str, Any]]] = []

    def fake_request(
        label: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> tuple[Any, int]:
        del json_body, auth
        calls.append((label, method, path, params or {}))
        return {}, 200

    monkeypatch.setattr(sampler, "request", fake_request)

    sampler.sample_next_iteration_read_fixtures("merchant-1", [{"uuid": "station-1"}], [])

    assert calls == [
        (
            "account_prepaid_stats",
            "GET",
            "/accounting/prepaid/prepaid_stats4merchant/merchant-1",
            {},
        ),
        (
            "account_prepaid_settlements",
            "GET",
            "/accounting/prepaid/list4merchant/merchant-1",
            {},
        ),
        ("account_tinkoff_opened_deals", "GET", "/accounting/tinkoff/prepaid/getOpenedDeals", {}),
        (
            "server_usage_statistics",
            "GET",
            "/accounting/statistics/myserverusageprepared",
            {},
        ),
        (
            "test_station_source",
            "GET",
            "/server-manager/servers/station-1",
            {"user_id": "merchant-1"},
        ),
        (
            "test_station_product_edit",
            "GET",
            "/server-manager/serverproduct/list4edit2/station-1/product-1",
            {},
        ),
    ]


def test_sampler_sanitizer_redacts_sensitive_values_and_uuid_keys() -> None:
    sanitizer = Sanitizer()

    sanitized = sanitizer.sanitize(
        {
            "perServerStats": {
                "4c09cc7e-0044-4936-9227-b1d95979b98e": {
                    "totalIncome": 123.45,
                    "10.0.0.1": "internal",
                }
            },
            "dealId": "12345678",
            "payout": 99.0,
            "sum": 120.0,
        }
    )

    assert sanitized == {
        "perServerStats": {
            "<uuid:1>": {
                "totalIncome": "<totalincome:redacted>",
                "<ip:1>": "internal",
            }
        },
        "dealId": "<dealid:redacted>",
        "payout": "<payout:redacted>",
        "sum": "<sum:redacted>",
    }


def test_sampler_next_iteration_product_edit_derives_product_from_test_station_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = DrovaSampler({"DROVA_PROXY_TOKEN": "token", "TEST_STATION_UUID": "station-1"})
    calls: list[tuple[str, str]] = []

    def fake_request(
        label: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> tuple[Any, int]:
        del method, params, json_body, auth
        calls.append((label, path))
        return {}, 200

    monkeypatch.setattr(sampler, "request", fake_request)

    sampler.sample_next_iteration_read_fixtures(
        "merchant-1",
        [{"uuid": "station-1"}],
        [{"productId": "derived-product"}],
    )

    assert (
        "test_station_product_edit",
        "/server-manager/serverproduct/list4edit2/station-1/derived-product",
    ) in calls


def test_sampler_next_iteration_skips_product_edit_without_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = DrovaSampler({"DROVA_PROXY_TOKEN": "token", "TEST_STATION_UUID": "station-1"})
    labels: list[str] = []

    def fake_request(
        label: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> tuple[Any, int]:
        del method, path, params, json_body, auth
        labels.append(label)
        return {}, 200

    monkeypatch.setattr(sampler, "request", fake_request)

    sampler.sample_next_iteration_read_fixtures("merchant-1", [{"uuid": "station-1"}], [])

    assert "test_station_product_edit" not in labels


def test_sampler_next_iteration_requires_test_station() -> None:
    sampler = DrovaSampler({"DROVA_PROXY_TOKEN": "token", "TEST_STATION_UUID": "station-1"})

    with pytest.raises(RuntimeError, match="TEST_STATION_UUID"):
        sampler.sample_next_iteration_read_fixtures("merchant-1", [{"uuid": "station-2"}], [])


def test_sampler_run_skips_writes_unless_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = DrovaSampler({"DROVA_PROXY_TOKEN": "token", "TEST_STATION_UUID": "station-1"})
    write_flows: list[tuple[list[dict[str, Any]], str]] = []

    def fake_request(
        label: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> tuple[Any, int]:
        del method, path, params, json_body, auth
        if label == "account":
            return {"uuid": "merchant-1"}, 200
        if label == "servers":
            return [{"uuid": "station-1", "published": True}], 200
        return [], 200

    def fake_write_flow(servers: list[dict[str, Any]], user_id: str) -> None:
        write_flows.append((servers, user_id))

    monkeypatch.setattr(sampler, "request", fake_request)
    monkeypatch.setattr(sampler, "sample_publish_write_flow", fake_write_flow)
    monkeypatch.setattr(sample_live_api, "write_json", lambda path, payload: None)

    sampler.run()
    assert write_flows == []

    sampler.run(include_writes=True)
    assert write_flows == [([{"uuid": "station-1", "published": True}], "merchant-1")]


def test_sampler_cli_requires_explicit_write_flag() -> None:
    assert sample_live_api.parse_args([]).include_writes is False
    assert sample_live_api.parse_args(["--include-writes"]).include_writes is True
