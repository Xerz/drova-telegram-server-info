from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from _pytest.config import Config, Parser
from _pytest.nodes import Item

from drova_bot.domain.models import (
    ChatProfile,
    Endpoint,
    ServerSource,
    ServerUsageStatistics,
    Session,
    Station,
    StationProduct,
    UsagePeriod,
    UsageStat,
)
from tests.live.harness import live_skip_reason

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "specs" / "v2" / "fixtures"


def pytest_addoption(parser: Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run opt-in live Drova API contract tests",
    )
    parser.addoption(
        "--run-live-write",
        action="store_true",
        default=False,
        help="run opt-in live write contract tests against TEST_STATION_UUID",
    )


def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
    run_live = bool(config.getoption("--run-live"))
    run_live_write = bool(config.getoption("--run-live-write"))
    for item in items:
        reason = live_skip_reason(
            is_live=item.get_closest_marker("live") is not None,
            is_live_write=item.get_closest_marker("live_write") is not None,
            run_live=run_live,
            run_live_write=run_live_write,
        )
        if reason is not None:
            item.add_marker(pytest.mark.skip(reason=reason))


def load_fixture(path: str) -> Any:
    return json.loads((FIXTURE_ROOT / path).read_text(encoding="utf-8"))


@pytest.fixture
def ui_state() -> dict[str, Any]:
    return cast("dict[str, Any]", load_fixture("ui/state.json"))


@pytest.fixture
def ui_stations() -> list[Station]:
    data = load_fixture("ui/stations.json")
    return [
        Station(
            uuid=item["uuid"],
            name=item["name"],
            state=item["state"],
            published=item["published"],
            verified=item.get("verified"),
            city_name=item.get("city_name"),
            groups_list=item.get("groups_list", []),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
        )
        for item in data
    ]


@pytest.fixture
def ui_sessions() -> list[Session]:
    data = load_fixture("ui/sessions.json")
    return [
        Session(
            uuid=item["uuid"],
            server_id=item["server_id"],
            merchant_id=item["merchant_id"],
            product_id=item["product_id"],
            client_id=item.get("client_id"),
            creator_ip=item.get("creator_ip"),
            created_on_ms=item["created_on"],
            finished_on_ms=item.get("finished_on"),
            billing_type=item.get("billing_type"),
            status=item.get("status"),
            score_text=item.get("score_text"),
        )
        for item in data["sessions"]
    ]


@pytest.fixture
def ui_products_by_station() -> dict[str, list[StationProduct]]:
    data = load_fixture("ui/station_products.json")
    return {
        station_id: [
            StationProduct(
                product_id=item["productId"],
                title=item["title"],
                enabled=item["enabled"],
                published=item["published"],
                available=item["available"],
            )
            for item in products
        ]
        for station_id, products in data.items()
    }


@pytest.fixture
def ui_endpoints_by_station() -> dict[str, list[Endpoint]]:
    data = load_fixture("ui/endpoints.json")
    return {
        station_id: [
            Endpoint(
                uuid=item["uuid"],
                server_id=item["server_id"],
                ip=item["ip"],
                base_port=item["base_port"],
                externally_routable=item.get("externally_routable"),
            )
            for item in endpoints
        ]
        for station_id, endpoints in data.items()
    }


@pytest.fixture
def ui_profile(ui_state: dict[str, Any]) -> ChatProfile:
    data = ui_state["chat_profile"]
    return ChatProfile(
        telegram_chat_id=data["telegram_chat_id"],
        drova_user_id=data["drova_user_id"],
        selected_station_id=data["selected_station_id"],
        session_limit=data["session_limit"],
        timezone=data["timezone"],
    )


@pytest.fixture
def ui_now(ui_state: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(
        ui_state["clock"]["now_utc"].replace("Z", "+00:00")
    ).astimezone(UTC)


@pytest.fixture
def ui_catalog(ui_state: dict[str, Any]) -> dict[str, str]:
    return dict(ui_state["product_catalog"])


@pytest.fixture
def ui_usage_statistics() -> ServerUsageStatistics:
    return ServerUsageStatistics(
        today=UsagePeriod(
            total=UsageStat(session_count=2, total_msecs=7_800_000),
            per_server={"station-online": UsageStat(session_count=2, total_msecs=7_800_000)},
            per_game={"product-a": UsageStat(session_count=2, total_msecs=7_800_000)},
        ),
        week=UsagePeriod(
            total=UsageStat(session_count=7, total_msecs=33_000_000),
            per_server={"station-online": UsageStat(session_count=7, total_msecs=33_000_000)},
            per_game={"product-a": UsageStat(session_count=7, total_msecs=33_000_000)},
        ),
        month=UsagePeriod(
            total=UsageStat(session_count=10, total_msecs=57_600_000),
            per_server={
                "station-online": UsageStat(session_count=8, total_msecs=43_200_000),
                "station-hidden": UsageStat(session_count=2, total_msecs=14_400_000),
            },
            per_game={
                "product-a": UsageStat(session_count=6, total_msecs=36_000_000),
                "product-b": UsageStat(session_count=4, total_msecs=21_600_000),
            },
        ),
    )


@pytest.fixture
def ui_server_source() -> ServerSource:
    return ServerSource(
        uuid="station-online",
        user_id="user-1",
        name="Alpha Station",
        description="<description:redacted>",
        state="LISTEN",
        published=True,
        verified=None,
        allow_desktop=False,
        disable_updates=True,
        product_ids=["product-a", "product-b"],
    )


def load_api_response(filename: str) -> Any:
    return load_fixture(f"api/{filename}")["response"]
