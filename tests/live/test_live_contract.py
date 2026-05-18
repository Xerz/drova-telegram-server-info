from __future__ import annotations

import pytest

from drova_bot.domain.models import Station
from drova_bot.drova.client import DrovaClient
from tests.live.harness import LiveSettings

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_read_contracts(live_client: DrovaClient) -> None:
    account = await live_client.get_account()
    products = await live_client.get_products_full()
    stations = await live_client.get_servers(account.uuid)
    account_sessions = await live_client.get_sessions(merchant_id=account.uuid, limit=5)

    assert account.uuid
    assert products
    assert len(account_sessions.sessions) <= 5

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


def _find_station(stations: list[Station], station_uuid: str) -> Station | None:
    return next((station for station in stations if station.uuid == station_uuid), None)
