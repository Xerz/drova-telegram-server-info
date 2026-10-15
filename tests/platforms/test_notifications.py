from datetime import timedelta
from pathlib import Path

from drova_bot.game_updates.models import GameFeed, UpdateObject
from drova_bot.game_updates.service import GameUpdatesService
from drova_bot.game_updates.storage import NotificationStore
from drova_bot.telegram.callbacks import CallbackSpec, parse_callback_data
from tests.platforms.test_contract import NOW, launcher
from tests.steam.test_notifications import page, store  # noqa: F401


async def test_linked_launcher_dedup_cancel_and_modes(store: NotificationStore) -> None:  # noqa: F811
    games = [
        UpdateObject(
            id=f"bsg:{key}",
            provider="bsg",
            external_id=key,
            title=key,
            linked_objects=["bsg:launcher"],
            coverage="launcher_only",
        )
        for key in ["eft", "arena"]
    ]
    source = launcher().model_dump(
        exclude={"stream_id", "seq", "previous_buildid", "observed_at", "branch"}
    )
    obj = UpdateObject.model_validate(source)
    await store.replace_feed(GameFeed(games=games, objects=[*games, obj]), NOW)
    service = GameUpdatesService(store, enabled=True, clock=lambda: NOW)
    for game in games:
        data = CallbackSpec(action="game_updates_add", product_id=game.id).pack()
        assert len(data.encode()) <= 64
        await service.callback(10001, parse_callback_data(data))
    await store.set_mode(10001, "selected", NOW)
    await store.ingest(page(launcher()))
    assert len(await store.pending(10001)) == 1
    due = NOW + timedelta(hours=1)
    jobs = await store.prepare(10001, due)
    assert len(jobs) == 1 and "Лаунчер" in jobs[0].text and "15.0" in jobs[0].text
    await store.select(10001, "bsg:eft", False, due)
    assert len(await store.pending(10001)) == 1
    await store.select(10001, "bsg:arena", False, due)
    assert await store.pending(10001) == []
    assert await store.prepare(10001, due) == []
    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(launcher(2)))
    assert not await store.pending(10001)
    await store.set_mode(10001, "all_supported", NOW)
    await store.ingest(page(launcher(3)))
    assert len(await store.pending(10001)) == 1
    await store.replace_feed(GameFeed(games=[], objects=[]), due)
    assert await store.prepare(10001, due) == []


def test_multiplatform_digest_fixture() -> None:
    from drova_bot.game_updates.renderers import render_digest

    expected = Path("specs/v2/fixtures/platforms/digest.html").read_text().rstrip("\n")
    assert render_digest([launcher()], "UTC") == [expected]


async def test_epic_search_selection_modes_queue_and_digest(store: NotificationStore) -> None:  # noqa: F811
    from drova_bot.game_updates.models import UpdateEvent
    from drova_bot.game_updates.renderers import render_digest

    game = UpdateObject(
        id="epic:fortnite",
        provider="epic",
        external_id="Fortnite",
        title="Fortnite",
        news_url="https://www.fortnite.com/news",
    )
    await store.replace_feed(GameFeed(games=[game], objects=[game]), NOW)
    event = UpdateEvent(
        **game.model_dump(exclude={"buildid", "version"}),
        stream_id="00000000-0000-0000-0000-000000000001",
        seq=1,
        previous_buildid="old",
        buildid="new",
        version="42.40",
        observed_at=NOW + timedelta(minutes=10),
    )
    expected = Path("specs/v2/fixtures/platforms/epic-digest.html").read_text().rstrip("\n")
    assert render_digest([event], "UTC") == [expected]
    service = GameUpdatesService(store, enabled=True, clock=lambda: NOW)
    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(event))
    assert not await store.pending(10001)
    packed = CallbackSpec(action="game_updates_add", product_id=game.id).pack()
    assert len(packed.encode()) <= 64
    await service.callback(10001, parse_callback_data(packed))
    await store.set_mode(10001, "selected", NOW)
    await store.ingest(page(event.model_copy(update={"seq": 2})))
    assert len(await store.pending(10001)) == 1
    await store.select(10001, game.id, False, NOW)
    assert not await store.pending(10001)
    await store.set_mode(10001, "all_supported", NOW)
    await store.ingest(page(event.model_copy(update={"seq": 3})))
    assert len(await store.pending(10001)) == 1
    await store.set_mode(10001, "off", NOW)
    assert not await store.pending(10001)


async def test_nte_resources_subscription_cancel_and_panel(store: NotificationStore) -> None:  # noqa: F811
    from drova_bot.game_updates.models import Subscription, UpdateEvent
    from drova_bot.game_updates.renderers import render_digest, render_panel
    from drova_bot.steam_watcher.registry import catalog_objects
    from tests.platforms.test_registry import product

    objects, _ = catalog_objects(
        [product("3d02d4c9-0dfb-44fd-aeb2-2a00d288bf11", "Neverness to Everness", "NTE")], {"nte"}
    )
    games = [o for o in objects if o.kind == "game"]
    resource = next(o for o in objects if o.kind == "resources")
    feed = GameFeed(games=games, objects=objects)
    await store.replace_feed(feed, NOW)
    panel = render_panel(
        feed, Subscription(), page=0, fetched_at=NOW.timestamp(), now=NOW, timezone="UTC"
    )
    assert "Отслеживаются только ресурсы" in panel.text
    event = UpdateEvent(
        **resource.model_dump(exclude={"buildid", "version"}),
        stream_id="00000000-0000-0000-0000-000000000001",
        seq=1,
        previous_buildid="old",
        buildid="new",
        version="1.3.10",
        observed_at=NOW + timedelta(minutes=10),
    )
    assert render_digest([event], "UTC") == [
        Path("specs/v2/fixtures/platforms/nte-digest.html").read_text().rstrip("\n")
    ]
    await store.set_mode(10001, "selected", NOW)
    await store.select(10001, "nte:global", True, NOW)
    await store.ingest(page(event))
    assert len(await store.pending(10001)) == 1
    await store.select(10001, "nte:global", False, NOW)
    assert not await store.pending(10001)
