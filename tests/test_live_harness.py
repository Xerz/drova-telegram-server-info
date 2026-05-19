from __future__ import annotations

from pathlib import Path

import pytest

from drova_bot.domain.models import StationProduct
from tests.live.harness import (
    DEFAULT_DROVA_BASE_URL,
    LiveSettings,
    MissingLiveEnvironment,
    choose_live_station_product_id,
    live_client_config,
    live_skip_reason,
    load_env_file,
    load_live_settings,
)


def test_live_env_parser_handles_comments_quotes_and_missing_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.specing"
    env_path.write_text(
        """
        # comment
        DROVA_PROXY_TOKEN="token"
        TEST_STATION_UUID='station-1'
        TEST_PRODUCT_UUID='product-1'
        HTTP_PROXY=
        MALFORMED_LINE
        HTTPS_PROXY=https://proxy.example
        """,
        encoding="utf-8",
    )

    assert load_env_file(tmp_path / "missing.env") == {}
    assert load_env_file(env_path) == {
        "DROVA_PROXY_TOKEN": "token",
        "TEST_STATION_UUID": "station-1",
        "TEST_PRODUCT_UUID": "product-1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "https://proxy.example",
    }


def test_live_settings_require_proxy_token_and_apply_defaults(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.env"
    env_path = tmp_path / ".env.specing"
    env_path.write_text("DROVA_PROXY_TOKEN=token\n", encoding="utf-8")

    with pytest.raises(MissingLiveEnvironment, match="DROVA_PROXY_TOKEN"):
        load_live_settings(missing_path)

    settings = load_live_settings(env_path)

    assert settings.drova_proxy_token == "token"
    assert settings.test_station_uuid is None
    assert settings.test_product_uuid is None
    assert settings.drova_base_url == DEFAULT_DROVA_BASE_URL


def test_live_client_config_prefers_https_proxy() -> None:
    settings = LiveSettings(
        drova_proxy_token="token",
        http_proxy="http://proxy.example",
        https_proxy="https://proxy.example",
        drova_base_url="https://drova.example",
    )

    config = live_client_config(settings)

    assert config.proxy_token == "token"
    assert config.base_url == "https://drova.example"
    assert config.proxy == "https://proxy.example"


def test_live_skip_reason_requires_explicit_flags() -> None:
    assert (
        live_skip_reason(
            is_live=True,
            is_live_write=False,
            run_live=False,
            run_live_write=False,
        )
        == "live contract tests require --run-live"
    )
    assert (
        live_skip_reason(
            is_live=True,
            is_live_write=True,
            run_live=True,
            run_live_write=False,
        )
        == "live write contract tests require --run-live-write"
    )
    assert (
        live_skip_reason(
            is_live=True,
            is_live_write=True,
            run_live=True,
            run_live_write=True,
        )
        is None
    )


def test_choose_live_station_product_id_prefers_configured_product_or_first() -> None:
    products = [
        StationProduct(
            product_id="product-a",
            title="A",
            enabled=True,
            published=True,
            available=True,
        ),
        StationProduct(
            product_id="product-b",
            title="B",
            enabled=True,
            published=True,
            available=True,
        ),
    ]

    assert choose_live_station_product_id(products, None) == "product-a"
    assert choose_live_station_product_id(products, "product-b") == "product-b"
    assert choose_live_station_product_id(products, "missing") is None
    assert choose_live_station_product_id([], None) is None
