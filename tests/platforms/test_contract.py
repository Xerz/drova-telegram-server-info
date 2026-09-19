from datetime import UTC, datetime, timedelta

from drova_bot.game_updates.models import Subscription, UpdateEvent, UpdateObject

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def launcher(seq: int = 1, minute: int = 10) -> UpdateEvent:
    return UpdateEvent(
        id="bsg:launcher",
        provider="bsg",
        external_id="launcher",
        kind="launcher",
        channel="global",
        title="BSG Launcher",
        news_url="https://www.escapefromtarkov.com/",
        related_games=["bsg:eft", "bsg:arena"],
        stream_id="00000000-0000-0000-0000-000000000001",
        seq=seq,
        previous_buildid="a",
        buildid="b",
        version="15.0",
        observed_at=NOW + timedelta(minutes=minute),
    )


def test_legacy_mapping_and_explicit_all() -> None:
    game = UpdateObject(appid=730, title="CS2")
    assert game.id == "steam:730"
    sub = Subscription(mode="all", enabled_since=NOW.timestamp(), selected={"730": 1})
    assert sub.selected == {"steam:730": 1}
    assert not sub.accepts(launcher())
    assert sub.model_copy(update={"mode": "all_supported"}).accepts(launcher())


def test_shared_launcher_activation_and_removal() -> None:
    sub = Subscription(
        mode="selected",
        enabled_since=NOW.timestamp(),
        selected={"bsg:eft": NOW.timestamp(), "bsg:arena": NOW.timestamp() + 1200},
    )
    assert sub.accepts(launcher())
    del sub.selected["bsg:eft"]
    assert not sub.accepts(launcher())
    assert sub.accepts(launcher(minute=30))
    del sub.selected["bsg:arena"]
    assert not sub.accepts(launcher(minute=30))
