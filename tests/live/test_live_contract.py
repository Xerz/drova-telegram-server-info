from __future__ import annotations

import pytest

from drova_bot.domain.models import Station
from drova_bot.drova.client import DrovaClient
from tests.live.harness import LiveSettings, choose_live_station_product_id

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_read_contracts(
    live_client: DrovaClient,
    live_settings: LiveSettings,
) -> None:
    account = await live_client.get_account()
    products = await live_client.get_products_full()
    stations = await live_client.get_servers(account.uuid)
    account_sessions = await live_client.get_sessions(merchant_id=account.uuid, limit=5)
    unused_promocodes = await live_client.get_unused_promocodes()
    prepaid_stats = await live_client.get_prepaid_stats(account.uuid)
    prepaid_settlements = await live_client.get_prepaid_settlements(account.uuid)
    opened_deals = await live_client.get_opened_prepaid_deals()
    usage_statistics = await live_client.get_server_usage_statistics()

    assert account.uuid
    assert products
    assert len(account_sessions.sessions) <= 5
    assert isinstance(unused_promocodes, list)
    assert prepaid_stats.merchant_id
    assert isinstance(prepaid_settlements, list)
    assert isinstance(opened_deals, list)
    assert usage_statistics.month.total.session_count >= 0

    if stations:
        source = await live_client.get_server_source(stations[0].uuid, account.uuid)
        assert source.uuid

    if live_settings.test_station_uuid and live_settings.test_product_uuid:
        product_edit = await live_client.get_server_product_edit(
            live_settings.test_station_uuid,
            live_settings.test_product_uuid,
        )
        assert product_edit.product_id

    for station in stations:
        station_sessions = await live_client.get_sessions(server_id=station.uuid, limit=5)
        station_products = await live_client.get_server_products(account.uuid, station.uuid)
        endpoints = await live_client.get_server_endpoints(station.uuid, limit=5)
        assert len(station_sessions.sessions) <= 5
        assert isinstance(station_products, list)
        assert isinstance(endpoints, list)


@pytest.mark.asyncio
@pytest.mark.live_write
async def test_live_publish_toggle_rolls_back(
    live_client: DrovaClient,
    live_settings: LiveSettings,
) -> None:
    if live_settings.test_station_uuid is None:
        pytest.skip("TEST_STATION_UUID is required in .env.specing")

    account = await live_client.get_account()
    stations = await live_client.get_servers(account.uuid)
    station = _find_station(stations, live_settings.test_station_uuid)
    if station is None:
        pytest.fail("TEST_STATION_UUID is not present in account stations")

    original_published = station.published
    toggled_published = not original_published
    rollback_error: BaseException | None = None

    try:
        await live_client.set_server_published(live_settings.test_station_uuid, toggled_published)
        toggled_station = _find_station(
            await live_client.get_servers(account.uuid),
            live_settings.test_station_uuid,
        )
        assert toggled_station is not None
        assert toggled_station.published is toggled_published
    finally:
        try:
            await live_client.set_server_published(
                live_settings.test_station_uuid,
                original_published,
            )
            restored_station = _find_station(
                await live_client.get_servers(account.uuid),
                live_settings.test_station_uuid,
            )
            if restored_station is None or restored_station.published is not original_published:
                raise AssertionError("TEST_STATION_UUID rollback verification failed")
        except BaseException as exc:
            rollback_error = exc

    if rollback_error is not None:
        raise AssertionError("TEST_STATION_UUID rollback failed") from rollback_error


@pytest.mark.asyncio
@pytest.mark.live_write
async def test_live_station_product_enabled_toggle_rolls_back(
    live_client: DrovaClient,
    live_settings: LiveSettings,
) -> None:
    if live_settings.test_station_uuid is None:
        pytest.skip("TEST_STATION_UUID is required in .env.specing")

    account = await live_client.get_account()
    stations = await live_client.get_servers(account.uuid)
    station = _find_station(stations, live_settings.test_station_uuid)
    if station is None:
        pytest.fail("TEST_STATION_UUID is not present in account stations")

    station_products = await live_client.get_server_products(
        account.uuid,
        live_settings.test_station_uuid,
    )
    product_id = choose_live_station_product_id(
        station_products,
        live_settings.test_product_uuid,
    )
    if product_id is None and live_settings.test_product_uuid is not None:
        pytest.fail("TEST_PRODUCT_UUID is not present in TEST_STATION_UUID products")
    if product_id is None:
        pytest.fail("TEST_STATION_UUID has no station products to toggle")

    original_product = await live_client.get_server_product_edit(
        live_settings.test_station_uuid,
        product_id,
    )
    original_enabled = original_product.enabled
    toggled_enabled = not original_enabled
    rollback_error: BaseException | None = None

    try:
        await live_client.set_server_product_enabled(
            live_settings.test_station_uuid,
            product_id,
            toggled_enabled,
        )
        toggled_product = await live_client.get_server_product_edit(
            live_settings.test_station_uuid,
            product_id,
        )
        assert toggled_product.enabled is toggled_enabled
    finally:
        try:
            await live_client.set_server_product_enabled(
                live_settings.test_station_uuid,
                product_id,
                original_enabled,
            )
            restored_product = await live_client.get_server_product_edit(
                live_settings.test_station_uuid,
                product_id,
            )
            if restored_product.enabled is not original_enabled:
                raise AssertionError("TEST_STATION_UUID product rollback verification failed")
        except BaseException as exc:
            rollback_error = exc

    if rollback_error is not None:
        raise AssertionError("TEST_STATION_UUID product rollback failed") from rollback_error


def _find_station(stations: list[Station], station_uuid: str) -> Station | None:
    return next((station for station in stations if station.uuid == station_uuid), None)
