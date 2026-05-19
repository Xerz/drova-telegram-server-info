from __future__ import annotations

from typing import Any

import pytest

from scripts.sample_live_api import DrovaSampler


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

    sampler.sample_next_iteration_read_fixtures("merchant-1", [{"uuid": "station-1"}])

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


def test_sampler_next_iteration_product_edit_requires_test_product(
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

    sampler.sample_next_iteration_read_fixtures("merchant-1", [{"uuid": "station-1"}])

    assert "test_station_product_edit" not in labels


def test_sampler_next_iteration_requires_test_station() -> None:
    sampler = DrovaSampler({"DROVA_PROXY_TOKEN": "token", "TEST_STATION_UUID": "station-1"})

    with pytest.raises(RuntimeError, match="TEST_STATION_UUID"):
        sampler.sample_next_iteration_read_fixtures("merchant-1", [{"uuid": "station-2"}])
