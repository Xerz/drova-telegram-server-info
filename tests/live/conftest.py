from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from drova_bot.drova.client import DrovaClient
from tests.live.harness import (
    LiveSettings,
    MissingLiveEnvironment,
    build_live_client,
    load_live_settings,
)


@pytest.fixture
def live_settings() -> LiveSettings:
    try:
        return load_live_settings()
    except MissingLiveEnvironment as exc:
        pytest.skip(str(exc))


@pytest.fixture
async def live_client(live_settings: LiveSettings) -> AsyncGenerator[DrovaClient]:
    async with build_live_client(live_settings) as client:
        yield client
